"""Crypto derivatives and flows: funding, OI, basis, implied vol, stablecoin supply, trend."""
from __future__ import annotations

import pandas as pd

from .. import config
from ..store import Store
from .common import clean, daily, indicator

HOURS_PER_YEAR = 24 * 365


def perps(store: Store) -> list[dict]:
    latest = store.query("SELECT * FROM perp_snapshots WHERE ts = (SELECT max(ts) FROM perp_snapshots)")
    if latest.empty:
        return []
    ts = latest["ts"].iloc[0]
    prior = store.query("""
        SELECT coin, arg_max(oi_usd, ts) AS oi_prev, arg_max(funding, ts) AS f_prev
        FROM perp_snapshots WHERE ts <= ?::TIMESTAMP - INTERVAL 23 HOUR GROUP BY coin""", [ts])
    df = latest.merge(prior, on="coin", how="left")
    watch = set(config.get("crypto.watch", []))
    held = set(store.query("SELECT DISTINCT symbol FROM positions WHERE asset_class LIKE 'crypto%'").get("symbol", []))
    top_n = int(config.get("crypto.top_n_by_oi", 25))
    df = df.sort_values("oi_usd", ascending=False)
    df = df[df["coin"].isin(watch | held) | (df.index.isin(df.head(top_n).index))]
    hot, cold = config.get("crypto.funding_hot_annualized", 0.5), config.get("crypto.funding_cold_annualized", -0.2)
    rows = []
    for r in df.to_dict("records"):
        f_ann = r["funding"] * HOURS_PER_YEAR
        rows.append({
            "coin": r["coin"], "mark": r["mark"],
            "chg_24h": (r["mark"] / r["prev_day_px"] - 1) * 100 if r["prev_day_px"] else None,
            "funding_hourly": r["funding"], "funding_ann": f_ann * 100,
            "oi_usd": r["oi_usd"],
            "oi_chg_24h": (r["oi_usd"] / r["oi_prev"] - 1) * 100 if r.get("oi_prev") else None,
            "volume_24h": r["volume_24h"], "premium_bps": r["premium"] * 1e4,
            "crowding": "crowded long" if f_ann >= hot else "crowded short" if f_ann <= cold else "",
            "held": r["coin"] in held, "watch": r["coin"] in watch,
        })
    return rows


def trend(store: Store, coin: str) -> dict | None:
    s = daily(store.series(f"hl:{coin}"))
    if len(s) < 50:
        return None
    px = float(s.iloc[-1])
    out = {"coin": coin, "price": px}
    for n in (20, 50, 200):
        if len(s) >= n:
            ma = float(s.iloc[-n:].mean())
            out[f"ma{n}"] = ma
            out[f"vs_ma{n}"] = (px / ma - 1) * 100
    hi = float(s.iloc[-365:].max())
    out["from_52w_high"] = (px / hi - 1) * 100
    out["rv_30d"] = float(s.pct_change().iloc[-30:].std() * (365 ** 0.5) * 100)
    return out


def snapshot(store: Store) -> dict:
    p = perps(store)
    total_oi = sum(r["oi_usd"] for r in p) if p else None
    oi_weighted_funding = (sum(r["funding_ann"] * r["oi_usd"] for r in p) / total_oi) if total_oi else None
    flows = [i for i in (
        indicator(store, "llama:stablecoin_supply", "Stablecoin Supply", "$"),
        indicator(store, "llama:defi_tvl", "DeFi TVL", "$"),
    ) if i]
    vol = [i for i in (indicator(store, f"deribit:DVOL:{c}", f"{c} DVOL", "") for c in config.get("crypto.dvol", [])) if i]
    etf = [i for i in (indicator(store, f"yf:{t}", n, "") for t, n in (config.get("yahoo.crypto_equities") or {}).items()) if i]
    trends = [t for t in (trend(store, c) for c in config.get("crypto.watch", [])) if t]
    return clean({
        "perps": p, "total_oi_usd": total_oi, "oi_weighted_funding_ann": oi_weighted_funding,
        "crowded": [r for r in p if r["crowding"]], "implied_vol": vol, "flows": flows,
        "crypto_equities": etf, "trends": trends,
    })


def funding_history(store: Store, coin: str, days: int = 14) -> list[dict]:
    df = store.query(f"""SELECT date_trunc('hour', ts) AS ts, avg(funding) * {HOURS_PER_YEAR} * 100 AS funding_ann,
                         avg(oi_usd) AS oi_usd, avg(mark) AS mark
                         FROM perp_snapshots WHERE coin = ? AND ts >= now()::TIMESTAMP - INTERVAL {int(days)} DAY
                         GROUP BY 1 ORDER BY 1""", [coin])
    return clean(df.assign(ts=df["ts"].astype(str)).to_dict("records")) if not df.empty else []
