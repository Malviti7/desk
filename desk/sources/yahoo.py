"""Yahoo Finance via yfinance (free, delayed, unofficial). Futures, indices, vol, FX,
commodities, ETFs, factors, sectors, and any equities you hold or watch."""
from __future__ import annotations

import pandas as pd

from .. import config
from ..store import Store

CATEGORY_MAP = {
    "futures": "futures", "indices": "indices", "vol": "vol", "fx": "fx",
    "commodities": "commodities", "credit": "credit", "factors": "factors",
    "sectors": "sectors", "crypto_equities": "equities",
}


def tickers(store: Store) -> dict[str, tuple[str, str]]:
    out: dict[str, tuple[str, str]] = {}
    y = config.get("yahoo", {})
    for group, cat in CATEGORY_MAP.items():
        for t, name in (y.get(group) or {}).items():
            out[t] = (name, cat)
    for t in config.get("equities.watchlist", []):
        out.setdefault(t, (t, "equities"))
    held = store.query(
        "SELECT DISTINCT symbol FROM positions WHERE price_source = 'yahoo' OR asset_class IN ('equity','etf')"
    )
    for t in held.get("symbol", []):
        out.setdefault(t, (t, "equities"))
    return out


def run(store: Store) -> int:
    import yfinance as yf

    universe = tickers(store)
    if not universe:
        return 0
    data = yf.download(list(universe), period="2y", interval="1d", auto_adjust=True,
                       progress=False, group_by="ticker", threads=True)
    n = 0
    for t, (name, cat) in universe.items():
        try:
            df = data[t] if isinstance(data.columns, pd.MultiIndex) else data
        except KeyError:
            continue
        if df is None or df.empty or "Close" not in df:
            continue
        n += store.upsert_series(f"yf:{t}", df["Close"], "yahoo", name, cat)
        if "Volume" in df and df["Volume"].fillna(0).sum() > 0:
            n += store.upsert_series(f"yf:{t}:volume", df["Volume"], "yahoo")
    return n
