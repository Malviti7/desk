"""Equities and positioning: COT, short interest, 13F crowding, earnings, sectors, factors."""
from __future__ import annotations

import pandas as pd

from ..store import Store
from .common import clean
from .regime import performance_table


def cot(store: Store) -> list[dict]:
    df = store.query("SELECT * FROM cot ORDER BY report_date")
    if df.empty:
        return []
    df["net"] = df["noncomm_long"] - df["noncomm_short"]
    df["net_pct_oi"] = df["net"] / df["open_interest"] * 100
    out = []
    for code, g in df.groupby("code"):
        g = g.sort_values("report_date")
        last = g.iloc[-1]
        hist = g["net"].iloc[-156:]  # ~3 years of weekly reports
        pct = float((hist <= last["net"]).mean() * 100) if len(hist) > 10 else None
        prev = g.iloc[-2] if len(g) > 1 else last
        out.append({
            "market": last["market"], "report_date": str(last["report_date"])[:10],
            "net_spec": last["net"], "net_pct_oi": last["net_pct_oi"],
            "chg_1w": last["net"] - prev["net"], "pctile_3y": pct,
            "signal": "extreme long" if pct is not None and pct >= 90 else "extreme short" if pct is not None and pct <= 10 else "",
        })
    return clean(sorted(out, key=lambda r: r["market"]))


def short_interest(store: Store) -> list[dict]:
    df = store.query("""SELECT symbol, arg_max(short_interest, settlement_date) AS si,
                               arg_max(days_to_cover, settlement_date) AS dtc,
                               max(settlement_date) AS as_of
                        FROM short_interest GROUP BY symbol ORDER BY dtc DESC""")
    return clean(df.assign(as_of=df["as_of"].astype(str)).to_dict("records")) if not df.empty else []


def crowding_13f(store: Store) -> dict:
    df = store.query("SELECT * FROM holdings_13f")
    if df.empty:
        return {"funds": [], "top_holdings": []}
    funds = (df.groupby(["fund", "period"])["value_usd"].sum().reset_index()
             .rename(columns={"value_usd": "aum_13f"}))
    top = (df.groupby("issuer").agg(holders=("fund", "nunique"), value_usd=("value_usd", "sum"))
           .sort_values(["holders", "value_usd"], ascending=False).head(25).reset_index())
    return clean({"funds": funds.assign(period=funds["period"].astype(str)).to_dict("records"),
                  "top_holdings": top.to_dict("records")})


def snapshot(store: Store) -> dict:
    return {
        "sectors": performance_table(store, "sectors"),
        "factors": performance_table(store, "factors"),
        "indices": performance_table(store, "indices"),
        "cot": cot(store),
        "short_interest": short_interest(store),
        "crowding_13f": crowding_13f(store),
    }
