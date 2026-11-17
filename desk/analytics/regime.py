"""Macro dashboard and the regime check: has anything changed in the backdrop?"""
from __future__ import annotations

import pandas as pd

from .. import config
from ..store import Store
from .common import clean, daily, indicator, returns

GREEN, AMBER, RED, NA = "green", "amber", "red", "na"


def _yahoo_group(store: Store, group: str) -> list[dict]:
    out = []
    for t, name in (config.get(f"yahoo.{group}") or {}).items():
        ind = indicator(store, f"yf:{t}", name, "")
        if ind:
            out.append(ind)
    return out


def _fred_group(store: Store, category: str) -> list[dict]:
    out = []
    for sid, (name, cat, unit) in (config.get("fred_series") or {}).items():
        if cat == category:
            ind = indicator(store, f"fred:{sid}", name, unit)
            if ind:
                out.append(ind)
    return out


def net_liquidity(store: Store) -> pd.Series:
    """Fed balance sheet minus TGA minus reverse repo, in $bn."""
    walcl = daily(store.series("fred:WALCL"))
    tga = daily(store.series("fred:WTREGEN"))
    rrp = daily(store.series("fred:RRPONTSYD"))
    if walcl.empty:
        return pd.Series(dtype=float)
    df = pd.concat({"w": walcl, "t": tga, "r": rrp}, axis=1).sort_index().ffill().dropna()
    return df["w"] / 1000 - df["t"] / 1000 - df["r"]


def rolling_corr(store: Store, a: str, b: str, window: int = 60) -> pd.Series:
    ra, rb = returns(store.series(a)), returns(store.series(b))
    df = pd.concat([ra, rb], axis=1, join="inner").dropna()
    if len(df) < window:
        return pd.Series(dtype=float)
    return df.iloc[:, 0].rolling(window).corr(df.iloc[:, 1]).dropna()


def macro_snapshot(store: Store) -> dict:
    nl = net_liquidity(store)
    liquidity = _fred_group(store, "liquidity")
    if not nl.empty:
        liquidity.insert(0, indicator(store, "calc:net_liquidity", "Net Liquidity (Fed BS - TGA - RRP)", "$bn", nl))
    corr = []
    for a, b, label in [("yf:SPY", "yf:TLT", "Stocks vs Bonds (60d)"),
                        ("yf:SPY", "hl:BTC", "Stocks vs BTC (60d)"),
                        ("yf:DX-Y.NYB", "hl:BTC", "Dollar vs BTC (60d)")]:
        c = rolling_corr(store, a, b)
        if not c.empty:
            corr.append(indicator(store, f"calc:corr:{a}:{b}", label, "corr", c))
    return clean({
        "rates": _fred_group(store, "rates"),
        "liquidity": liquidity,
        "credit": _fred_group(store, "credit") + _yahoo_group(store, "credit"),
        "fx": _yahoo_group(store, "fx") + _fred_group(store, "fx"),
        "vol": _yahoo_group(store, "vol"),
        "commodities": _yahoo_group(store, "commodities"),
        "futures": _yahoo_group(store, "futures"),
        "indices": _yahoo_group(store, "indices"),
        "economy": _fred_group(store, "economy"),
        "correlations": corr,
        "curve": yield_curve(store),
    })


def yield_curve(store: Store) -> dict:
    tenors = [("3M", "fred:DGS3MO"), ("2Y", "fred:DGS2"), ("10Y", "fred:DGS10"), ("30Y", "fred:DGS30")]
    now, month_ago = [], []
    for label, sid in tenors:
        s = daily(store.series(sid, days=60))
        if s.empty:
            continue
        past = s[s.index <= s.index[-1] - pd.Timedelta(days=30)]
        now.append({"tenor": label, "yield": float(s.iloc[-1])})
        month_ago.append({"tenor": label, "yield": float(past.iloc[-1]) if not past.empty else None})
    return {"now": now, "month_ago": month_ago}


# ------------------------------------------------------------------ regime signals
def _sig(name: str, status: str, value: str, why: str) -> dict:
    return {"name": name, "status": status, "value": value, "why": why}


def regime(store: Store) -> dict:
    a = config.get("alerts", {}) or {}
    sigs: list[dict] = []

    vix, vix3m = daily(store.series("yf:^VIX")), daily(store.series("yf:^VIX3M"))
    if not vix.empty and not vix3m.empty:
        ratio = float(vix.iloc[-1] / vix3m.iloc[-1])
        st = RED if ratio >= a.get("vix_backwardation", 1.0) else AMBER if ratio > 0.92 else GREEN
        sigs.append(_sig("VIX term structure", st, f"VIX/VIX3M {ratio:.2f}",
                         "Backwardation (>1) means near-term fear exceeds longer-term: stress regime."))

    hy = indicator(store, "fred:BAMLH0A0HYM2", "HY OAS", "%")
    if hy:
        w = hy["chg_1w"] or 0
        st = RED if w >= a.get("hy_oas_weekly_widening_bp", 25) else AMBER if w >= 10 or (hy["pctile_1y"] or 0) > 80 else GREEN
        sigs.append(_sig("Credit spreads", st, f"HY {hy['value']:.2f}% ({w:+.0f}bp 1w)",
                         "Credit tends to lead equities when risk breaks."))

    jpy = indicator(store, "yf:USDJPY=X", "USDJPY", "")
    if jpy:
        w = jpy["chg_1w"] or 0
        st = RED if w <= -a.get("usdjpy_weekly_drop_pct", 2.0) else AMBER if w <= -1.0 else GREEN
        sigs.append(_sig("Yen carry", st, f"USDJPY {jpy['value']:.2f} ({w:+.1f}% 1w)",
                         "Sharp yen strength forces carry unwinds across risk assets."))

    dxy = indicator(store, "yf:DX-Y.NYB", "DXY", "")
    if dxy:
        w = dxy["chg_1m"] or 0
        st = AMBER if w >= 2.5 else GREEN
        sigs.append(_sig("Dollar", st, f"DXY {dxy['value']:.1f} ({w:+.1f}% 1m)",
                         "A fast-rising dollar tightens global financial conditions."))

    move = indicator(store, "yf:^MOVE", "MOVE", "")
    if move:
        st = RED if move["value"] >= 140 else AMBER if move["value"] >= 110 else GREEN
        sigs.append(_sig("Rates vol", st, f"MOVE {move['value']:.0f}", "High rates vol bleeds into every asset's risk premium."))

    c = rolling_corr(store, "yf:SPY", "yf:TLT")
    if not c.empty:
        v = float(c.iloc[-1])
        st = AMBER if v > 0.3 else GREEN
        sigs.append(_sig("Stock/bond correlation", st, f"{v:+.2f} (60d)",
                         "Positive means bonds are not hedging equities; diversification is weaker."))

    nl = net_liquidity(store)
    if len(nl) > 30:
        chg = float(nl.iloc[-1] - nl[nl.index <= nl.index[-1] - pd.Timedelta(days=28)].iloc[-1])
        st = AMBER if chg < -100 else GREEN
        sigs.append(_sig("Net liquidity", st, f"${nl.iloc[-1]:,.0f}bn ({chg:+,.0f}bn 4w)",
                         "Draining liquidity has been a headwind for high-beta assets, crypto especially."))

    two, ff = daily(store.series("fred:DGS2")), daily(store.series("fred:DFEDTARU"))
    if not two.empty and not ff.empty:
        spread = (float(two.iloc[-1]) - (float(ff.iloc[-1]) - 0.125)) * 100
        lean = "cuts" if spread < -15 else "hikes" if spread > 15 else "on hold"
        sigs.append(_sig("Fed path (2Y vs funds)", GREEN, f"{spread:+.0f}bp, market leans {lean}",
                         "Proxy for FedWatch: 2Y yield vs the midpoint of the funds range."))

    nfci = indicator(store, "fred:NFCI", "NFCI", "z")
    if nfci:
        st = RED if nfci["value"] > 0 else AMBER if (nfci["chg_1m"] or 0) > 0.1 else GREEN
        sigs.append(_sig("Financial conditions", st, f"NFCI {nfci['value']:.2f}",
                         "Positive NFCI = tighter than average conditions."))

    dv = indicator(store, "deribit:DVOL:BTC", "BTC DVOL", "")
    if dv:
        w = dv["chg_1w"] or 0
        st = RED if w >= a.get("btc_dvol_jump_pct", 20) else AMBER if w >= 10 else GREEN
        sigs.append(_sig("Crypto implied vol", st, f"BTC DVOL {dv['value']:.0f} ({w:+.0f}% 1w)",
                         "Jumps in implied vol usually precede or accompany deleveraging."))

    from ..integrations import outlook as ibd_outlook

    o = ibd_outlook(store)
    if o:
        exp = f", exposure {o['exposure_pct']:.0f}%" if o.get("exposure_pct") is not None else ""
        sigs.insert(0, _sig("IBD market outlook", o["color"], f"{o['label']}{exp}",
                            "IBD's read on market direction from distribution days and follow-throughs."))

    reds = sum(s["status"] == RED for s in sigs)
    ambers = sum(s["status"] == AMBER for s in sigs)
    if not sigs:
        label = "No data yet"
    elif reds >= 3:
        label = "Stress"
    elif reds >= 1 or ambers >= 3:
        label = "Caution"
    elif ambers >= 1:
        label = "Neutral"
    else:
        label = "Risk-on"
    return clean({"label": label, "reds": reds, "ambers": ambers, "signals": sigs})


def performance_table(store: Store, group: str) -> list[dict]:
    """1d / 1w / 1m / YTD performance for sectors, factors, etc."""
    rows = []
    for t, name in (config.get(f"yahoo.{group}") or {}).items():
        s = daily(store.series(f"yf:{t}"))
        if len(s) < 2:
            continue
        ytd_base = s[s.index < pd.Timestamp(year=s.index[-1].year, month=1, day=1)]
        ind = indicator(store, f"yf:{t}", name, "", s)
        rows.append({"ticker": t, "name": name, "price": ind["value"], "d1": ind["chg_1d"],
                     "w1": ind["chg_1w"], "m1": ind["chg_1m"],
                     "ytd": (float(s.iloc[-1] / ytd_base.iloc[-1]) - 1) * 100 if not ytd_base.empty else None})
    return clean(rows)
