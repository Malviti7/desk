"""Synthetic demo data so the dashboard, API, and MCP tools work before any keys are set.
Run `desk demo` into a separate DB (default data/demo.duckdb). Never mixes with real data."""
from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

from . import config
from .store import Store, utcnow

RNG = np.random.default_rng(7)


def _walk(start: float, n: int, vol: float, drift: float = 0.0) -> np.ndarray:
    return start * np.exp(np.cumsum(RNG.normal(drift, vol, n)))


def _rate(start: float, n: int, vol_bp: float) -> np.ndarray:
    return start + np.cumsum(RNG.normal(0, vol_bp / 100, n))


LEVELS = {
    "ES=F": 6050, "NQ=F": 21800, "RTY=F": 2350, "ZN=F": 111, "^GSPC": 6040, "^NDX": 21700, "^N225": 39500,
    "^HSI": 20500, "^STOXX50E": 5050, "^VIX9D": 15, "^VIX": 16.5, "^VIX3M": 18.5, "^VIX6M": 19.8, "^MOVE": 95,
    "DX-Y.NYB": 104, "USDJPY=X": 152, "EURUSD=X": 1.07, "CNH=X": 7.25, "CL=F": 71, "HG=F": 4.4, "GC=F": 2650,
    "NG=F": 3.1, "HYG": 79, "LQD": 109, "TLT": 92, "SPY": 600, "MTUM": 210, "VLUE": 110, "QUAL": 180,
    "USMV": 90, "IWM": 235, "IBIT": 52, "ETHA": 24, "COIN": 290, "MSTR": 380,
}
CRYPTO = {"BTC": 92000, "ETH": 3200, "SOL": 220, "HYPE": 28, "DOGE": 0.38, "XRP": 1.4, "SUI": 3.9, "AVAX": 42,
          "LINK": 22, "ENA": 1.1, "kPEPE": 0.02, "WIF": 2.8, "TAO": 480, "FARTCOIN": 1.2, "AAVE": 300}
FRED_LEVELS = {
    "DGS3MO": (4.35, 2), "DGS2": (4.15, 5), "DGS10": (4.35, 5), "DGS30": (4.55, 4), "DFII10": (2.0, 4),
    "T10YIE": (2.33, 2), "DFF": (4.58, 0.2), "DFEDTARU": (4.75, 0), "SOFR": (4.6, 0.5),
    "BAMLH0A0HYM2": (2.9, 3), "BAMLC0A0CM": (0.85, 1), "NFCI": (-0.5, 1),
    "ICSA": (220000, 0), "UNRATE": (4.2, 0), "CPIAUCSL": (315, 0),
}


def seed(store: Store, days: int = 520) -> None:
    idx = pd.bdate_range(end=date.today(), periods=int(days * 5 / 7))
    cidx = pd.date_range(end=date.today(), periods=days, freq="D")
    y = config.get("yahoo", {})
    names = {t: n for g in y.values() for t, n in (g or {}).items()}
    for t in set(names) | set(config.get("equities.watchlist", [])) | {"NVDA"}:
        lvl = LEVELS.get(t, RNG.uniform(50, 500))
        vol = 0.045 if t.startswith("^VIX") or t == "^MOVE" else 0.012
        s = pd.Series(_walk(lvl, len(idx), vol), index=idx)
        s = s / s.iloc[-1] * lvl
        store.upsert_series(f"yf:{t}", s, "demo", names.get(t, t), "demo")
        store.upsert_series(f"yf:{t}:volume", pd.Series(RNG.uniform(5e6, 3e7, len(idx)), index=idx), "demo")
    for sid, (name, cat, unit) in config.get("fred_series", {}).items():
        lvl, v = FRED_LEVELS.get(sid, (None, None))
        if sid in ("WALCL", "WTREGEN", "WRESBAL"):
            base = {"WALCL": 6_900_000, "WTREGEN": 800_000, "WRESBAL": 3_200_000}[sid]
            s = pd.Series(_walk(base, len(idx), 0.002), index=idx)
        elif sid == "RRPONTSYD":
            s = pd.Series(np.maximum(_walk(400, len(idx), 0.03, -0.004), 50), index=idx)
        elif sid == "DTWEXBGS":
            s = pd.Series(_walk(124, len(idx), 0.003), index=idx)
        elif lvl is not None:
            path = _rate(lvl, len(idx), v) if v else np.full(len(idx), lvl)
            s = pd.Series(path - path[-1] + lvl, index=idx)
        else:
            continue
        store.upsert_series(f"fred:{sid}", s, "demo", name, cat, unit)
    btc = None
    for c, lvl in CRYPTO.items():
        vol = 0.028 if c == "BTC" else 0.045
        base = _walk(1, len(cidx), vol)
        if btc is not None and c != "BTC":
            base = np.exp(0.7 * np.log(btc / btc[0]) + 0.3 * np.log(base))
        s = pd.Series(base / base[-1] * lvl, index=cidx)
        if c == "BTC":
            btc = base
        store.upsert_series(f"hl:{c}", s, "demo", f"{c} (Hyperliquid)", "crypto")
        store.upsert_series(f"hl:{c}:volume", pd.Series(RNG.uniform(1e8, 2e9, len(cidx)) / lvl, index=cidx), "demo")
    for c, lvl in (("BTC", 52), ("ETH", 68)):
        store.upsert_series(f"deribit:DVOL:{c}", pd.Series(_walk(lvl, len(cidx), 0.03), index=cidx), "demo", f"{c} DVOL", "crypto_vol")
    store.upsert_series("llama:stablecoin_supply", pd.Series(_walk(2.05e11, len(cidx), 0.002, 0.0006), index=cidx), "demo", "Stablecoin Supply", "crypto_flows", "$")
    store.upsert_series("llama:defi_tvl", pd.Series(_walk(1.2e11, len(cidx), 0.015), index=cidx), "demo", "DeFi TVL", "crypto_flows", "$")

    # perp snapshots: hourly for 2 days
    rows = []
    now = utcnow().replace(minute=0, second=0, microsecond=0)
    for h in range(48, -1, -1):
        ts = now - timedelta(hours=h)
        for c, lvl in CRYPTO.items():
            mark = lvl * (1 + RNG.normal(0, 0.004) - h * 0.0003)
            oi_coins = 2.5e9 / lvl * (3 if c == "BTC" else 1) * (1 + 0.002 * (48 - h))
            funding = {"HYPE": 0.00009, "SOL": 0.00004, "FARTCOIN": -0.00004}.get(c, 0.0000125) + RNG.normal(0, 0.000004)
            rows.append({"ts": ts, "venue": "hyperliquid", "coin": c, "mark": mark, "oracle": mark,
                         "funding": funding, "open_interest": oi_coins, "oi_usd": oi_coins * mark,
                         "volume_24h": RNG.uniform(2e8, 4e9), "premium": RNG.normal(0, 0.0003),
                         "prev_day_px": lvl * (1 + RNG.normal(0, 0.03))})
    store.insert_df("perp_snapshots", pd.DataFrame(rows))

    # positions
    px = lambda c: CRYPTO[c]  # noqa: E731
    pos = [
        ("hyperliquid", "hyperliquid", "HYPE", "crypto_spot", 9000, 18.0, px("HYPE"), None, None),
        ("hyperliquid", "hyperliquid", "USDC", "cash", 40000, 1.0, 1.0, None, None),
        ("hyperliquid", "hyperliquid", "BTC", "crypto_perp", 1.2, 88000, px("BTC"), 10, 61000),
        ("hyperliquid", "hyperliquid", "SOL", "crypto_perp", -150, 228, px("SOL"), 5, 330),
        ("hyperliquid", "hyperliquid", "ETH", "crypto_perp", 20, 3100, px("ETH"), 8, 2350),
        ("coinbase", "coinbase", "ETH", "crypto_spot", 6, None, px("ETH"), None, None),
        ("coinbase", "coinbase", "USDC", "cash", 15000, 1.0, 1.0, None, None),
        ("ibkr", "manual", "NVDA", "equity", 150, 120.5, None, None, None),
        ("ibkr", "manual", "COIN", "equity", 200, 240.0, None, None, None),
        ("ibkr", "manual", "TLT", "etf", -400, 95.0, None, None, None),
    ]
    prow = []
    for acct, venue, sym, ac, qty, entry, price, lev, liq in pos:
        if price is None:
            price = float(store.series(f"yf:{sym}").iloc[-1])
        prow.append({"ts": now, "account": acct, "venue": venue, "symbol": sym, "asset_class": ac, "qty": qty,
                     "entry_px": entry, "price": price, "notional": qty * price,
                     "unrealized_pnl": (price - entry) * qty if entry else None, "leverage": lev,
                     "liquidation_px": liq, "margin_used": abs(qty * price) / lev if lev else None,
                     "price_source": "yahoo" if venue == "manual" else "hyperliquid"})
    store.insert_df("positions", pd.DataFrame(prow))
    hl = [p for p in prow if p["venue"] == "hyperliquid"]
    perp_ntl = sum(abs(p["notional"]) for p in hl if p["asset_class"] == "crypto_perp")
    eq_now = sum(p["notional"] for p in hl if p["asset_class"] != "crypto_perp") + sum(p["unrealized_pnl"] or 0 for p in hl if p["asset_class"] == "crypto_perp")
    for h in range(24 * 30, -1, -6):
        store.execute("INSERT INTO account_state VALUES (?, ?, ?, ?, ?, ?, ?, ?)", [
            now - timedelta(hours=h), "hyperliquid", "hyperliquid",
            eq_now * (1 + 0.08 * np.sin(h / 90) + RNG.normal(0, 0.01)), perp_ntl * 0.03, perp_ntl * 0.12, eq_now * 0.3, "{}"])

    store.execute("""INSERT INTO theses VALUES
        ('BTC','long','Spot ETF inflows + liquidity turning; trend intact above 50DMA',84000,110000,'FOMC','2026-12-09',now(),'demo'),
        ('SOL','short','Funding hot, alt beta fading vs BTC',240,180,NULL,NULL,now(),'demo'),
        ('NVDA','long','AI capex cycle, earnings beat streak',105,160,'Earnings','2026-11-19',now(),'demo'),
        ('COIN','long','Volume rebound with crypto beta',215,340,NULL,NULL,now(),'demo')""")
    store.execute("""INSERT INTO ideas VALUES
        (nextval('ideas_seq'),'ETH','long',3000,'below','Add on a flush into prior breakout level','open',now(),'demo'),
        (nextval('ideas_seq'),'HYPE','short-perp-hedge',35,'above','Hedge spot with perps if funding >80%','open',now(),'demo')""")

    cal = [(date.today() + timedelta(days=d), k, n, det) for d, k, n, det in [
        (1, "macro", "Unemployment Insurance Weekly Claims", "8:30am"), (2, "earnings", "NVDA earnings", "AMC EPS est 0.85 HELD"),
        (3, "macro", "Personal Income and Outlays", "8:30am"), (5, "crypto", "Deribit monthly expiry", ""),
        (8, "macro", "Employment Situation", "8:30am"), (23, "macro", "FOMC decision", "2:00pm ET")]]
    store.insert_df("calendar", pd.DataFrame(cal, columns=["date", "kind", "name", "detail"]).assign(source="demo"))

    heads = [("Fed's Waller says December cut still on the table as inflation cools", "fed,inflation"),
             ("Treasury yields climb after strong retail sales print", "rates"),
             ("Bitcoin ETFs see third straight day of inflows", "$BTC"),
             ("Hyperliquid volumes hit record as perp DEX share grows", "$HYPE"),
             ("Solana memecoin activity cools; funding stays elevated", "$SOL"),
             ("Nvidia suppliers signal strong data center orders ahead of earnings", "$NVDA"),
             ("Bank of Japan official flags possible rate hike, yen firms", "japan"),
             ("SEC roundtable on crypto custody rules scheduled", "crypto-reg,$COIN")]
    nrows = [{"id": hashlib.sha1(h.encode()).hexdigest()[:16], "ts": utcnow() - timedelta(hours=i * 2),
              "source": "demo", "title": h, "url": "https://example.com", "summary": "", "tags": t}
             for i, (h, t) in enumerate(heads)]
    store.insert_df("news", pd.DataFrame(nrows))

    wk = pd.date_range(end=date.today(), periods=160, freq="W-TUE")
    crows = []
    for code, mkt in config.get("cftc_markets", {}).items():
        net = _rate(0, len(wk), 2000)
        for d, n in zip(wk, net):
            oi = 500000.0
            crows.append({"report_date": d.date(), "code": code, "market": mkt, "open_interest": oi,
                          "noncomm_long": 150000 + n * 100, "noncomm_short": 150000 - n * 100,
                          "comm_long": 200000.0, "comm_short": 200000.0})
    store.insert_df("cot", pd.DataFrame(crows))
    store.insert_df("short_interest", pd.DataFrame([
        {"symbol": s, "settlement_date": date.today() - timedelta(days=10), "short_interest": RNG.uniform(5e6, 6e7),
         "avg_daily_volume": RNG.uniform(5e6, 5e7), "days_to_cover": RNG.uniform(0.5, 6)}
        for s in config.get("equities.watchlist", [])]))
    hrows = []
    for cik, fund in config.get("sec_13f_filers", {}).items():
        for iss in ["NVIDIA CORP", "MICROSOFT CORP", "APPLE INC", "AMAZON COM INC", "META PLATFORMS INC", "COINBASE GLOBAL INC"]:
            if RNG.random() > 0.3:
                hrows.append({"cik": cik, "fund": fund, "period": date(2026, 9, 30), "issuer": iss, "cusip": iss[:9],
                              "value_usd": RNG.uniform(1e8, 5e9), "shares": RNG.uniform(1e5, 1e7)})
    store.insert_df("holdings_13f", pd.DataFrame(hrows))
    # Coinalyze-style cross-venue snapshots (now and ~24h ago) and daily history
    venues = [("Binance", 8, 0.45), ("Bybit", 8, 0.22), ("OKX", 8, 0.13), ("Hyperliquid", 1, 0.20)]
    base_oi = {"BTC": 6.2e10, "ETH": 3.1e10, "SOL": 7.5e9, "HYPE": 2.4e9}
    fund8h = {"BTC": 0.008, "ETH": 0.009, "SOL": 0.018, "HYPE": 0.035}
    xrows = []
    for back, growth in ((24, 0.96), (0, 1.0)):
        ts = now - timedelta(hours=back)
        for c, tot in base_oi.items():
            for ex, hrs, share in venues:
                f = fund8h[c] * (1 + RNG.normal(0, 0.2)) * hrs / 8
                xrows.append({"ts": ts, "coin": c, "exchange": ex, "symbol": f"{c}USDT_PERP.{ex[0]}",
                              "oi_usd": tot * share * growth, "funding_pct": f, "predicted_funding_pct": f * 1.05,
                              "funding_ann": f / 100 * (24 / hrs) * 365,
                              "liq_long_24h": tot * share * RNG.uniform(0.0005, 0.003),
                              "liq_short_24h": tot * share * RNG.uniform(0.0003, 0.0015)})
    store.insert_df("xvenue_snapshots", pd.DataFrame(xrows))
    for c, tot in base_oi.items():
        oi = pd.Series(_walk(1, len(cidx), 0.03), index=cidx)
        store.upsert_series(f"cz:{c}:oi_usd", oi / oi.iloc[-1] * tot, "demo", f"{c} OI, all venues", "crypto_derivs", "$")
        store.upsert_series(f"cz:{c}:funding_ann", pd.Series(np.clip(_rate(fund8h[c] * 3 * 365, len(cidx), 150), -20, 80), index=cidx),
                            "demo", f"{c} OI-weighted funding (ann %)", "crypto_derivs", "pct")
        store.upsert_series(f"cz:{c}:liq_long", pd.Series(RNG.gamma(1.5, tot * 0.001, len(cidx)), index=cidx), "demo", f"{c} long liquidations", "crypto_derivs", "$")
        store.upsert_series(f"cz:{c}:liq_short", pd.Series(RNG.gamma(1.5, tot * 0.0007, len(cidx)), index=cidx), "demo", f"{c} short liquidations", "crypto_derivs", "$")

    # MarketSurge-style ratings and IBD outlook
    pats = ["Cup with handle", "Flat base", "Double bottom", "Ascending base", "Cup without handle", "Base on base"]
    mrows = []
    for i, sym in enumerate(config.get("equities.watchlist", [])):
        px = float(store.series(f"yf:{sym}").iloc[-1])
        offset = [0.02, 0.07, -0.03, 0.01, 0.12, -0.06, 0.04, 0.0, 0.09, -0.01][i % 10]
        mrows.append({"symbol": sym, "as_of": date.today(), "list_name": "IBD 50 (demo)", "name": sym,
                      "composite": float(99 - i * 3), "eps_rating": float(95 - i * 2), "rs": float(97 - i * 4),
                      "smr": "AB"[i % 2], "acc_dis": "ABC"[i % 3] + ("+" if i % 2 else ""), "group_rank": float(5 + i * 7),
                      "pattern": pats[i % len(pats)], "buy_point": round(px / (1 + offset), 2),
                      "pct_off_high": round(-abs(offset) * 100, 1), "price": px, "raw": "{}"})
    store.insert_df("ms_ratings", pd.DataFrame(mrows))
    store.execute("INSERT INTO ms_outlook VALUES (now(), 'confirmed_uptrend', 80, 'demo', 'demo')")
    for i, (sym, act, px, msg) in enumerate([
            ("NVDA", "buy", None, "Breakout above pivot on 1.6x volume"),
            ("BTC", "alert", None, "Reclaimed 50-day line"),
            ("META", "sell", None, "Closed below 21-day EMA")]):
        p = float(store.series(f"yf:{sym}").iloc[-1]) if sym != "BTC" else CRYPTO["BTC"]
        store.execute("INSERT INTO tv_alerts VALUES (nextval('tv_seq'), ?, ?, ?, ?, 'D', ?, '{}')",
                      [now - timedelta(hours=1 + i * 3), sym, act, p, msg])

    for j in ["fred", "yahoo", "hyperliquid_market", "hyperliquid_account", "news", "cftc"]:
        store.log(j, "ok", 0, "demo data")
