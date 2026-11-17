"""Other free crypto sources: Deribit DVOL (implied vol) and DefiLlama (stablecoins, TVL)."""
from __future__ import annotations

import time

import pandas as pd

from .. import config
from ..store import Store
from . import get_json


def run_deribit(store: Store) -> int:
    end = int(time.time() * 1000)
    start = end - 400 * 86_400_000
    n = 0
    for ccy in config.get("crypto.dvol", ["BTC", "ETH"]):
        data = get_json("https://www.deribit.com/api/v2/public/get_volatility_index_data", {
            "currency": ccy, "start_timestamp": start, "end_timestamp": end, "resolution": "1D"})
        rows = (data.get("result") or {}).get("data") or []
        if rows:
            s = pd.Series([r[4] for r in rows], index=pd.to_datetime([r[0] for r in rows], unit="ms"))
            n += store.upsert_series(f"deribit:DVOL:{ccy}", s, "deribit", f"{ccy} DVOL", "crypto_vol", "vol pts")
    return n


def run_defillama(store: Store) -> int:
    n = 0
    stables = get_json("https://stablecoins.llama.fi/stablecoincharts/all")
    if stables:
        s = pd.Series(
            [float((r.get("totalCirculatingUSD") or {}).get("peggedUSD", 0)) for r in stables],
            index=pd.to_datetime([int(r["date"]) for r in stables], unit="s"),
        )
        n += store.upsert_series("llama:stablecoin_supply", s.iloc[-800:], "defillama",
                                 "Stablecoin Supply", "crypto_flows", "$")
    tvl = get_json("https://api.llama.fi/v2/historicalChainTvl")
    if tvl:
        s = pd.Series([float(r["tvl"]) for r in tvl], index=pd.to_datetime([int(r["date"]) for r in tvl], unit="s"))
        n += store.upsert_series("llama:defi_tvl", s.iloc[-800:], "defillama", "DeFi TVL", "crypto_flows", "$")
    return n
