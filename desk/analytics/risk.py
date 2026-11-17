"""Portfolio and risk: exposures, betas, factor exposures, VaR, stress tests, liquidity,
margin headroom, protected-spot check, thesis tracking, correlations, P&L attribution.

All numbers are computed from data in the store, deterministically. Nothing here trades.
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from .. import config
from ..store import Store
from .common import clean, daily

FACTOR_ETFS = {"MTUM": "Momentum", "VLUE": "Value", "QUAL": "Quality", "USMV": "Min Vol", "IWM": "Size (small)"}


# ------------------------------------------------------------------ positions
def positions(store: Store) -> pd.DataFrame:
    df = store.query("SELECT * FROM positions WHERE qty <> 0")
    if df.empty:
        return df
    df["notional"] = df["notional"].fillna(0.0)
    df["is_crypto"] = df["asset_class"].str.startswith("crypto")
    return df


def price_series(store: Store, symbol: str, is_crypto: bool) -> pd.Series:
    ids = [f"hl:{symbol}", f"yf:{symbol}-USD"] if is_crypto else [f"yf:{symbol}"]
    for sid in ids:
        s = daily(store.series(sid, days=800))
        if len(s) > 30:
            return s
    return pd.Series(dtype=float)


def volume_series(store: Store, symbol: str, is_crypto: bool) -> pd.Series:
    ids = [f"hl:{symbol}:volume", f"yf:{symbol}-USD:volume"] if is_crypto else [f"yf:{symbol}:volume"]
    for sid in ids:
        s = daily(store.series(sid, days=60))
        if not s.empty:
            return s
    return pd.Series(dtype=float)


def returns_frame(store: Store, pos: pd.DataFrame, days: int) -> pd.DataFrame:
    """Daily returns per symbol. Equity returns are 0 on weekends so crypto days still count."""
    cols = {}
    for sym, is_c in pos[["symbol", "is_crypto"]].drop_duplicates("symbol").itertuples(index=False):
        s = price_series(store, sym, is_c)
        if not s.empty:
            cols[sym] = s.pct_change()
    if not cols:
        return pd.DataFrame()
    df = pd.DataFrame(cols).sort_index()
    df = df[df.index >= df.index[-1] - pd.Timedelta(days=days)]
    return df.fillna(0.0)


def _beta(r: pd.Series, m: pd.Series) -> float | None:
    df = pd.concat([r, m], axis=1, join="inner").dropna()
    df = df[(df.iloc[:, 0] != 0) & (df.iloc[:, 1] != 0)]  # drop non-trading days
    if len(df) < 30 or df.iloc[:, 1].var() == 0:
        return None
    return float(np.cov(df.iloc[:, 0], df.iloc[:, 1])[0, 1] / df.iloc[:, 1].var())


def betas(store: Store, pos: pd.DataFrame) -> dict[str, dict]:
    spy = daily(store.series("yf:SPY")).pct_change()
    btc = price_series(store, "BTC", True).pct_change()
    out = {}
    for sym, is_c in pos[["symbol", "is_crypto"]].drop_duplicates("symbol").itertuples(index=False):
        if sym in ("USD", "USDC", "USDT"):
            continue
        r = price_series(store, sym, is_c).pct_change()
        r = r[r.index >= r.index[-1] - pd.Timedelta(days=180)] if not r.empty else r
        out[sym] = {"beta_spx": _beta(r, spy) if not spy.empty else None,
                    "beta_btc": (1.0 if sym == "BTC" else _beta(r, btc)) if not btc.empty else None,
                    "vol_ann": float(r.std() * np.sqrt(365 if is_c else 252) * 100) if len(r) > 20 else None}
    return out


# ------------------------------------------------------------------ exposures
def exposures(pos: pd.DataFrame, b: dict[str, dict]) -> dict:
    risk = pos[pos["asset_class"] != "cash"]
    gross = float(risk["notional"].abs().sum())
    net = float(risk["notional"].sum())
    by_class = risk.groupby("asset_class")["notional"].agg(net="sum", gross=lambda x: x.abs().sum()).reset_index()
    by_acct = pos.groupby("account")["notional"].agg(net="sum", gross=lambda x: x.abs().sum()).reset_index()
    eq = risk[~risk["is_crypto"]]
    cr = risk[risk["is_crypto"]]
    beta_spx_net = float(sum(r.notional * (b.get(r.symbol, {}).get("beta_spx") or 1.0) for r in eq.itertuples()))
    beta_btc_net = float(sum(r.notional * (b.get(r.symbol, {}).get("beta_btc") or 1.0) for r in cr.itertuples()))
    sym_gross = risk.groupby("symbol")["notional"].sum().abs().sort_values(ascending=False)
    top5 = float(sym_gross.head(5).sum() / gross * 100) if gross else 0.0
    hhi = float(((sym_gross / gross) ** 2).sum()) if gross else 0.0
    return {
        "gross": gross, "net": net, "long": float(risk.loc[risk.notional > 0, "notional"].sum()),
        "short": float(risk.loc[risk.notional < 0, "notional"].sum()),
        "cash": float(pos.loc[pos.asset_class == "cash", "notional"].sum()),
        "beta_adj_net_spx": beta_spx_net, "beta_adj_net_btc": beta_btc_net,
        "top5_pct_gross": top5, "effective_positions": (1 / hhi) if hhi else None,
        "by_asset_class": by_class.to_dict("records"), "by_account": by_acct.to_dict("records"),
    }


def factor_exposures(store: Store, pos: pd.DataFrame) -> list[dict]:
    """Dollar exposure of equity positions to market and style factors (long-short vs SPY)."""
    eq = pos[(~pos["is_crypto"]) & (pos["asset_class"] != "cash")]
    if eq.empty:
        return []
    spy = daily(store.series("yf:SPY")).pct_change()
    facs = {"Market": spy}
    for t, name in FACTOR_ETFS.items():
        s = daily(store.series(f"yf:{t}")).pct_change()
        if not s.empty:
            facs[name] = s - spy
    X = pd.DataFrame(facs).dropna().iloc[-250:]
    if len(X) < 60:
        return []
    totals = {k: 0.0 for k in X.columns}
    for r in eq.itertuples():
        y = price_series(store, r.symbol, False).pct_change()
        df = pd.concat([y.rename("y"), X], axis=1, join="inner").dropna()
        if len(df) < 60:
            continue
        A = np.column_stack([np.ones(len(df)), df[X.columns].values])
        coef = np.linalg.lstsq(A, df["y"].values, rcond=None)[0][1:]
        for k, c in zip(X.columns, coef):
            totals[k] += float(c * r.notional)
    return [{"factor": k, "dollar_exposure": v} for k, v in totals.items()]


# ------------------------------------------------------------------ VaR
def var(store: Store, pos: pd.DataFrame) -> dict:
    risk = pos[pos["asset_class"] != "cash"]
    if risk.empty:
        return {}
    lookback = int(config.get("portfolio.var_lookback_days", 250))
    R = returns_frame(store, risk, lookback)
    if R.empty or len(R) < 30:
        return {"note": "Not enough price history yet"}
    w = risk.groupby("symbol")["notional"].sum().reindex(R.columns).fillna(0.0)
    pnl = R.values @ w.values
    pnl = pd.Series(pnl, index=R.index)
    q95, q99 = np.percentile(pnl, 5), np.percentile(pnl, 1)
    return {
        "lookback_days": int(len(pnl)),
        "var_95": float(-q95), "var_99": float(-q99),
        "es_95": float(-pnl[pnl <= q95].mean()), "es_99": float(-pnl[pnl <= q99].mean()),
        "worst_day": float(-pnl.min()), "worst_day_date": pnl.idxmin().date().isoformat(),
        "daily_vol": float(pnl.std()),
        "pnl_history": [{"date": d.date().isoformat(), "pnl": float(v)} for d, v in pnl.iloc[-120:].items()],
    }


def correlation(store: Store, pos: pd.DataFrame, days: int = 90) -> dict:
    risk = pos[pos["asset_class"] != "cash"]
    R = returns_frame(store, risk, days)
    if R.shape[1] < 2:
        return {"symbols": list(R.columns), "matrix": []}
    C = R.corr().round(2)
    return {"symbols": list(C.columns), "matrix": C.values.tolist()}


# ------------------------------------------------------------------ stress
def stress(store: Store, pos: pd.DataFrame, b: dict[str, dict], scenario: dict, account: dict | None) -> dict:
    overrides = {k.upper(): v for k, v in (scenario.get("overrides") or {}).items()}
    spx, btc = float(scenario.get("spx", 0.0)), float(scenario.get("btc", 0.0))
    rows, total = [], 0.0
    hl_pnl, hl_perp_gross_before, hl_perp_gross_after = 0.0, 0.0, 0.0
    for r in pos.itertuples():
        if r.asset_class == "cash":
            continue
        bb = b.get(r.symbol, {})
        if r.symbol in overrides:
            shock = float(overrides[r.symbol])
        elif r.is_crypto:
            shock = btc * (bb.get("beta_btc") if bb.get("beta_btc") is not None else 1.0)
        else:
            shock = spx * (bb.get("beta_spx") if bb.get("beta_spx") is not None else 1.0)
        pnl = r.notional * shock
        total += pnl
        rows.append({"symbol": r.symbol, "account": r.account, "asset_class": r.asset_class,
                     "notional": r.notional, "shock_pct": shock * 100, "pnl": pnl})
        if r.venue == "hyperliquid":
            hl_pnl += pnl
            if r.asset_class == "crypto_perp":
                hl_perp_gross_before += abs(r.notional)
                hl_perp_gross_after += abs(r.notional * (1 + shock))
    out = {"name": scenario.get("name", "custom"), "spx": spx, "btc": btc, "overrides": overrides,
           "total_pnl": total, "positions": sorted(rows, key=lambda x: x["pnl"])}
    if account:
        eq, mm = account["account_value"], account["maint_margin"] or 0.0
        mm_after = mm * (hl_perp_gross_after / hl_perp_gross_before) if hl_perp_gross_before else mm
        eq_after = eq + hl_pnl
        protected_value_after = sum(
            x["notional"] * (1 + x["shock_pct"] / 100) for x in rows
            if x["account"] == "hyperliquid" and x["asset_class"] == "crypto_spot"
            and x["symbol"] in account["protected"])
        out["hyperliquid"] = {
            "equity_before": eq, "equity_after": eq_after, "maint_before": mm, "maint_after": mm_after,
            "headroom_after_pct": ((eq_after - mm_after) / eq_after * 100) if eq_after > 0 else -100.0,
            "liquidation": eq_after <= mm_after,
            # Buffer = equity that is NOT your protected spot, above maintenance margin.
            "buffer_before_protected_after": eq_after - protected_value_after - mm_after,
            "protected_spot_at_risk": (eq_after - protected_value_after - mm_after) < 0,
        }
    return out


# ------------------------------------------------------------------ margin / account
def hyperliquid_account(store: Store, pos: pd.DataFrame) -> dict | None:
    st = store.query("SELECT * FROM account_state WHERE account = 'hyperliquid' ORDER BY ts DESC LIMIT 1")
    if st.empty:
        return None
    s = st.iloc[0]
    eq, mm = float(s["account_value"]), float(s["maint_margin"] or 0)
    protected = [p.upper() for p in config.get("portfolio.protected_spot", [])]
    hl = pos[pos["venue"] == "hyperliquid"]
    prot_val = float(hl[hl["symbol"].isin(protected) & (hl["asset_class"] == "crypto_spot")]["notional"].sum())
    perps = hl[hl["asset_class"] == "crypto_perp"]
    liq = []
    for r in perps.itertuples():
        if r.liquidation_px and r.price:
            dist = abs(r.price - r.liquidation_px) / r.price
            liq.append({"symbol": r.symbol, "price": r.price, "liquidation_px": r.liquidation_px,
                        "distance_pct": dist * 100})
    hist = store.query("""SELECT date_trunc('hour', ts) AS ts, avg(account_value) AS equity FROM account_state
                          WHERE account = 'hyperliquid' AND ts >= now()::TIMESTAMP - INTERVAL 30 DAY
                          GROUP BY 1 ORDER BY 1""")
    dd = None
    if not hist.empty:
        peak = float(hist["equity"].max())
        dd = (eq / peak - 1) * 100 if peak else None
    return {
        "as_of": str(s["ts"]), "account_value": eq, "maint_margin": mm, "margin_used": float(s["margin_used"] or 0),
        "withdrawable": float(s["withdrawable"] or 0),
        "headroom_pct": ((eq - mm) / eq * 100) if eq else None,
        "protected": protected, "protected_spot_value": prot_val,
        "buffer_before_protected": eq - prot_val - mm,
        "perp_gross": float(perps["notional"].abs().sum()), "perp_net": float(perps["notional"].sum()),
        "leverage_on_free_equity": float(perps["notional"].abs().sum() / max(eq - prot_val, 1e-9)) if eq else None,
        "liquidation_distances": sorted(liq, key=lambda x: x["distance_pct"]),
        "drawdown_30d_pct": dd,
        "equity_history": [{"ts": str(t), "equity": float(e)} for t, e in hist.itertuples(index=False)],
    }


# ------------------------------------------------------------------ book view
def book(store: Store, pos: pd.DataFrame, b: dict[str, dict]) -> list[dict]:
    theses = store.query("SELECT * FROM theses").set_index("symbol").to_dict("index")
    part = float(config.get("portfolio.adv_participation", 0.2))
    gross = float(pos.loc[pos.asset_class != "cash", "notional"].abs().sum()) or 1.0
    rows = []
    for r in pos.itertuples():
        s = price_series(store, r.symbol, r.is_crypto) if r.asset_class != "cash" else pd.Series(dtype=float)
        prev = float(s.iloc[-2]) if len(s) > 2 else None
        pnl_1d = (r.price - prev) * r.qty if (prev and r.price) else None
        vol = volume_series(store, r.symbol, r.is_crypto)
        adv = float(vol.iloc[-21:-1].mean()) if len(vol) > 5 else None
        days_exit = abs(r.qty) / (part * adv) if adv else None
        t = theses.get(r.symbol, {})
        stop, target = t.get("stop"), t.get("target")
        is_long = r.qty > 0
        d_stop = d_tgt = None
        breached = False
        if r.price and stop and not pd.isna(stop):
            d_stop = (r.price - stop) / r.price * 100 * (1 if is_long else -1)
            breached = d_stop <= 0
        if r.price and target and not pd.isna(target):
            d_tgt = (target - r.price) / r.price * 100 * (1 if is_long else -1)
        bb = b.get(r.symbol, {})
        rows.append({
            "account": r.account, "venue": r.venue, "symbol": r.symbol, "asset_class": r.asset_class,
            "qty": r.qty, "price": r.price, "entry_px": r.entry_px, "notional": r.notional,
            "pct_gross": abs(r.notional) / gross * 100 if r.asset_class != "cash" else None,
            "unrealized_pnl": r.unrealized_pnl, "pnl_1d": pnl_1d, "leverage": r.leverage,
            "liquidation_px": r.liquidation_px, "beta_spx": bb.get("beta_spx"), "beta_btc": bb.get("beta_btc"),
            "vol_ann": bb.get("vol_ann"), "days_to_exit": days_exit,
            "thesis": t.get("thesis"), "stop": stop, "target": target, "catalyst": t.get("catalyst"),
            "catalyst_date": str(t["catalyst_date"])[:10] if t.get("catalyst_date") is not None and not pd.isna(t.get("catalyst_date")) else None,
            "dist_to_stop_pct": d_stop, "dist_to_target_pct": d_tgt, "stop_breached": breached,
        })
    return sorted(rows, key=lambda x: -abs(x["notional"] or 0))


def _n(x) -> float:
    return 0.0 if x is None or pd.isna(x) else float(x)


# ------------------------------------------------------------------ public entry points
def portfolio(store: Store) -> dict:
    pos = positions(store)
    if pos.empty:
        return clean({"positions": [], "exposures": {}, "note": "No positions loaded yet"})
    b = betas(store, pos)
    bk = book(store, pos, b)
    return clean({
        "positions": bk, "exposures": exposures(pos, b),
        "pnl_1d_total": sum(_n(x["pnl_1d"]) for x in bk),
        "unrealized_total": sum(_n(x["unrealized_pnl"]) for x in bk),
        "hyperliquid": hyperliquid_account(store, pos),
    })


def _scenario_account(store: Store, pos: pd.DataFrame) -> dict | None:
    hl = hyperliquid_account(store, pos)
    if not hl:
        return None
    return {"account_value": hl["account_value"], "maint_margin": hl["maint_margin"], "protected": hl["protected"]}


def _with_hypotheticals(pos: pd.DataFrame, adds: list[dict]) -> pd.DataFrame:
    """Append what-if positions: [{symbol, notional, asset_class?, venue?}]. Negative notional = short."""
    rows = []
    for a in adds or []:
        ac = a.get("asset_class", "crypto_perp")
        venue = a.get("venue", "hyperliquid" if ac.startswith("crypto") else "manual")
        rows.append({"account": "what-if" if venue != "hyperliquid" else "hyperliquid", "venue": venue,
                     "symbol": str(a["symbol"]).upper(), "asset_class": ac, "qty": 0.0, "price": None,
                     "notional": float(a["notional"]), "is_crypto": ac.startswith("crypto")})
    return pd.concat([pos, pd.DataFrame(rows)], ignore_index=True) if rows else pos


def run_stress(store: Store, scenario: dict) -> dict:
    pos = _with_hypotheticals(positions(store), scenario.get("add") or [])
    if pos.empty:
        return {"note": "No positions"}
    return clean(stress(store, pos, betas(store, pos), scenario, _scenario_account(store, pos)))


def report(store: Store) -> dict:
    pos = positions(store)
    if pos.empty:
        return clean({"note": "No positions loaded yet"})
    b = betas(store, pos)
    acct = _scenario_account(store, pos)
    scen = [stress(store, pos, b, s, acct) for s in config.get("stress_scenarios", [])]
    for s in scen:
        s["positions"] = s["positions"][:8]
    bk = book(store, pos, b)
    liq = [{"symbol": x["symbol"], "days_to_exit": x["days_to_exit"], "notional": x["notional"]}
           for x in bk if x["days_to_exit"] is not None]
    return clean({
        "as_of": date.today().isoformat(),
        "exposures": exposures(pos, b),
        "factor_exposures": factor_exposures(store, pos),
        "var": var(store, pos),
        "stress": scen,
        "worst_stress": min(scen, key=lambda s: s["total_pnl"]) if scen else None,
        "liquidity": sorted(liq, key=lambda x: -(x["days_to_exit"] or 0)),
        "correlation": correlation(store, pos),
        "hyperliquid": hyperliquid_account(store, pos),
        "stops": [{"symbol": x["symbol"], "price": x["price"], "stop": x["stop"],
                   "dist_to_stop_pct": x["dist_to_stop_pct"], "breached": x["stop_breached"]}
                  for x in bk if x["stop"] is not None and not pd.isna(x["stop"])],
    })
