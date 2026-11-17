"""Coinalyze (free API key): cross-exchange open interest, funding, predicted funding, and
liquidations. Rate limit is 40 calls/min and every symbol in a request counts as one call,
so this module throttles itself and keeps the market list small and focused on what you
watch or hold.

Docs: https://api.coinalyze.net/v1/doc  (auth: `api_key` header)
"""
from __future__ import annotations

import time
from collections import defaultdict
from datetime import datetime, timezone

import pandas as pd

from .. import config
from ..store import Store, utcnow
from . import client

BASE = "https://api.coinalyze.net/v1"
CALLS_PER_MIN = 36  # stay under the 40/min limit
_last_call = [0.0]


def _key() -> str:
    k = config.env("COINALYZE_API_KEY")
    if not k:
        raise RuntimeError("COINALYZE_API_KEY not set (free at coinalyze.net, account > API)")
    return k


def _get(path: str, params: dict | None = None, cost: int = 1):
    """GET with throttling by call cost and Retry-After handling on 429."""
    wait = _last_call[0] + cost * 60.0 / CALLS_PER_MIN - time.time()
    if wait > 0:
        time.sleep(wait)
    for _ in range(4):
        with client(headers={"api_key": _key()}) as c:
            r = c.get(f"{BASE}/{path}", params=params)
        _last_call[0] = time.time()
        if r.status_code == 429:
            time.sleep(float(r.headers.get("Retry-After", 10)) + 1)
            continue
        if r.status_code == 401:
            raise RuntimeError("Coinalyze rejected the API key")
        r.raise_for_status()
        return r.json()
    raise RuntimeError("Coinalyze rate limited repeatedly")


def _chunks(xs: list, n: int = 20):
    for i in range(0, len(xs), n):
        yield xs[i:i + n]


# ------------------------------------------------------------------ market selection
def coins(store: Store) -> list[str]:
    cz = config.get("coinalyze", {}) or {}
    out = list(dict.fromkeys(cz.get("coins") or config.get("crypto.watch", [])))
    if cz.get("include_held", True):
        held = store.query("SELECT DISTINCT symbol FROM positions WHERE asset_class LIKE 'crypto%'")
        for s in held.get("symbol", []):
            if s not in out and s not in ("USDC", "USDT", "USD"):
                out.append(s)
    return out[: int(cz.get("max_coins", 10))]


def markets(store: Store) -> list[dict]:
    """Pick perpetual markets for our coins on the preferred exchanges."""
    cz = config.get("coinalyze", {}) or {}
    prefer = [e.lower() for e in cz.get("exchanges", ["Binance", "Bybit", "OKX", "Hyperliquid", "Bitget", "Deribit"])]
    exch = {e["code"]: e["name"] for e in _get("exchanges", cost=1)}
    allm = _get("future-markets", cost=1)
    want = {c.upper() for c in coins(store)}
    picked: dict[tuple[str, str], dict] = {}
    for m in allm:
        if not m.get("is_perpetual"):
            continue
        base = str(m.get("base_asset", "")).upper()
        name = exch.get(m.get("exchange"), str(m.get("exchange")))
        if base not in want or not any(p in name.lower() for p in prefer):
            continue
        quote = str(m.get("quote_asset", "")).upper()
        rank = {"USDT": 0, "USD": 1, "USDC": 2}.get(quote, 3)
        key = (base, name)
        if key not in picked or rank < picked[key]["_rank"]:
            picked[key] = {**m, "exchange_name": name, "_rank": rank}
    return list(picked.values())


def _funding_hours(exchange: str) -> float:
    m = (config.get("coinalyze.funding_interval_hours") or {})
    for k, v in m.items():
        if k.lower() in exchange.lower():
            return float(v)
    return float(m.get("default", 8))


# ------------------------------------------------------------------ snapshot job
def run(store: Store) -> int:
    mk = markets(store)
    if not mk:
        return 0
    syms = [m["symbol"] for m in mk]
    by_sym = {m["symbol"]: m for m in mk}
    oi, fr, pfr = {}, {}, {}
    for ch in _chunks(syms):
        s = ",".join(ch)
        for r in _get("open-interest", {"symbols": s, "convert_to_usd": "true"}, cost=len(ch)):
            oi[r["symbol"]] = r.get("value")
        for r in _get("funding-rate", {"symbols": s}, cost=len(ch)):
            fr[r["symbol"]] = r.get("value")
        for r in _get("predicted-funding-rate", {"symbols": s}, cost=len(ch)):
            pfr[r["symbol"]] = r.get("value")
    now_s = int(time.time())
    liq = defaultdict(lambda: [0.0, 0.0])
    for ch in _chunks(syms):
        rows = _get("liquidation-history", {"symbols": ",".join(ch), "interval": "1hour",
                                            "from": now_s - 86400, "to": now_s, "convert_to_usd": "true"}, cost=len(ch))
        for r in rows:
            for h in r.get("history", []):
                liq[r["symbol"]][0] += float(h.get("l") or 0)
                liq[r["symbol"]][1] += float(h.get("s") or 0)
    ts = utcnow()
    out = []
    for s in syms:
        m = by_sym[s]
        hrs = _funding_hours(m["exchange_name"])
        f = fr.get(s)
        out.append({
            "ts": ts, "coin": str(m["base_asset"]).upper(), "exchange": m["exchange_name"], "symbol": s,
            "oi_usd": oi.get(s), "funding_pct": f, "predicted_funding_pct": pfr.get(s),
            # Coinalyze reports funding in percent per funding interval.
            "funding_ann": (float(f) / 100.0) * (24 / hrs) * 365 if f is not None else None,
            "liq_long_24h": liq[s][0], "liq_short_24h": liq[s][1],
        })
    store.execute("DELETE FROM xvenue_snapshots WHERE ts < now()::TIMESTAMP - INTERVAL 30 DAY")
    return store.insert_df("xvenue_snapshots", pd.DataFrame(out))


# ------------------------------------------------------------------ daily history backfill
def run_history(store: Store, days: int = 365) -> int:
    """Daily aggregated OI, OI-weighted funding, and liquidations per coin, as series cz:*."""
    mk = markets(store)
    if not mk:
        return 0
    now_s = int(time.time())
    frm = now_s - days * 86400
    syms = [m["symbol"] for m in mk]
    by_sym = {m["symbol"]: m for m in mk}
    oi_hist: dict[str, pd.Series] = {}
    f_hist: dict[str, pd.Series] = {}
    liq_l: dict[str, pd.Series] = {}
    liq_s: dict[str, pd.Series] = {}

    def to_series(hist, field):
        if not hist:
            return pd.Series(dtype=float)
        return pd.Series([float(h.get(field) or 0) for h in hist],
                         index=pd.to_datetime([h["t"] for h in hist], unit="s").normalize())

    for ch in _chunks(syms):
        s = ",".join(ch)
        p = {"symbols": s, "interval": "daily", "from": frm, "to": now_s}
        for r in _get("open-interest-history", {**p, "convert_to_usd": "true"}, cost=len(ch)):
            oi_hist[r["symbol"]] = to_series(r.get("history"), "c")
        for r in _get("funding-rate-history", p, cost=len(ch)):
            f_hist[r["symbol"]] = to_series(r.get("history"), "c")
        for r in _get("liquidation-history", {**p, "convert_to_usd": "true"}, cost=len(ch)):
            liq_l[r["symbol"]] = to_series(r.get("history"), "l")
            liq_s[r["symbol"]] = to_series(r.get("history"), "s")

    n = 0
    for coin in sorted({str(m["base_asset"]).upper() for m in mk}):
        cs = [s for s in syms if str(by_sym[s]["base_asset"]).upper() == coin]
        oi = pd.DataFrame({s: oi_hist.get(s, pd.Series(dtype=float)) for s in cs}).fillna(0.0)
        if oi.empty:
            continue
        total = oi.sum(axis=1)
        ann = pd.DataFrame({s: f_hist.get(s, pd.Series(dtype=float)) / 100.0 * (24 / _funding_hours(by_sym[s]["exchange_name"])) * 365
                            for s in cs}).reindex(oi.index)
        w = (ann * oi).sum(axis=1) / total.replace(0, pd.NA)
        n += store.upsert_series(f"cz:{coin}:oi_usd", total, "coinalyze", f"{coin} OI, all venues", "crypto_derivs", "$")
        n += store.upsert_series(f"cz:{coin}:funding_ann", w.astype(float) * 100, "coinalyze",
                                 f"{coin} OI-weighted funding (ann %)", "crypto_derivs", "pct")
        ll = pd.DataFrame({s: liq_l.get(s, pd.Series(dtype=float)) for s in cs}).sum(axis=1)
        ls = pd.DataFrame({s: liq_s.get(s, pd.Series(dtype=float)) for s in cs}).sum(axis=1)
        n += store.upsert_series(f"cz:{coin}:liq_long", ll, "coinalyze", f"{coin} long liquidations", "crypto_derivs", "$")
        n += store.upsert_series(f"cz:{coin}:liq_short", ls, "coinalyze", f"{coin} short liquidations", "crypto_derivs", "$")
    return n
