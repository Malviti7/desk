"""Hyperliquid public info API (free, no key). Market data for all perps, daily candles,
and your account (read-only by wallet address)."""
from __future__ import annotations

import json
import time

import pandas as pd

from .. import config
from ..store import Store, utcnow
from . import post_json

INFO = "https://api.hyperliquid.xyz/info"


def _f(x, default=0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def all_mids() -> dict[str, float]:
    return {k: _f(v) for k, v in post_json(INFO, {"type": "allMids"}).items() if not k.startswith("@")}


def run_market(store: Store) -> int:
    meta, ctxs = post_json(INFO, {"type": "metaAndAssetCtxs"})
    now = utcnow()
    rows = []
    for asset, ctx in zip(meta["universe"], ctxs):
        mark = _f(ctx.get("markPx"))
        oi = _f(ctx.get("openInterest"))
        rows.append({
            "ts": now, "venue": "hyperliquid", "coin": asset["name"], "mark": mark,
            "oracle": _f(ctx.get("oraclePx")), "funding": _f(ctx.get("funding")),
            "open_interest": oi, "oi_usd": oi * mark, "volume_24h": _f(ctx.get("dayNtlVlm")),
            "premium": _f(ctx.get("premium")), "prev_day_px": _f(ctx.get("prevDayPx")),
        })
    df = pd.DataFrame(rows)
    # keep 30 days of snapshots
    store.execute("DELETE FROM perp_snapshots WHERE ts < now()::TIMESTAMP - INTERVAL 30 DAY")
    return store.insert_df("perp_snapshots", df)


def candle_coins(store: Store) -> list[str]:
    coins = set(config.get("crypto.watch", []))
    top = store.query("""
        SELECT coin FROM perp_snapshots
        WHERE ts = (SELECT max(ts) FROM perp_snapshots)
        ORDER BY oi_usd DESC LIMIT ?""", [int(config.get("crypto.top_n_by_oi", 25))])
    coins.update(top.get("coin", []))
    held = store.query("SELECT DISTINCT symbol FROM positions WHERE asset_class LIKE 'crypto%'")
    coins.update(s for s in held.get("symbol", []) if s not in ("USDC", "USDT", "USD"))
    return sorted(coins)


def run_candles(store: Store, days: int = 400) -> int:
    end = int(time.time() * 1000)
    start = end - days * 86_400_000
    n = 0
    for coin in candle_coins(store):
        try:
            candles = post_json(INFO, {"type": "candleSnapshot", "req": {
                "coin": coin, "interval": "1d", "startTime": start, "endTime": end}})
        except Exception:  # noqa: BLE001  (spot-only tokens have no perp candles)
            continue
        if not candles:
            continue
        idx = pd.to_datetime([c["t"] for c in candles], unit="ms")
        close = pd.Series([_f(c["c"]) for c in candles], index=idx)
        vol = pd.Series([_f(c["v"]) for c in candles], index=idx)
        n += store.upsert_series(f"hl:{coin}", close, "hyperliquid", f"{coin} (Hyperliquid)", "crypto")
        n += store.upsert_series(f"hl:{coin}:volume", vol, "hyperliquid")
    return n


def run_account(store: Store) -> int:
    addr = config.env("HYPERLIQUID_ADDRESS")
    if not addr:
        raise RuntimeError("HYPERLIQUID_ADDRESS not set")
    now = utcnow()
    perp = post_json(INFO, {"type": "clearinghouseState", "user": addr})
    spot = post_json(INFO, {"type": "spotClearinghouseState", "user": addr})
    mids = all_mids()

    rows = []
    for ap in perp.get("assetPositions", []):
        p = ap.get("position", {})
        coin, szi = p.get("coin"), _f(p.get("szi"))
        if not coin or szi == 0:
            continue
        px = mids.get(coin) or (_f(p.get("positionValue")) / abs(szi))
        rows.append({
            "ts": now, "account": "hyperliquid", "venue": "hyperliquid", "symbol": coin,
            "asset_class": "crypto_perp", "qty": szi, "entry_px": _f(p.get("entryPx")),
            "price": px, "notional": szi * px, "unrealized_pnl": _f(p.get("unrealizedPnl")),
            "leverage": _f((p.get("leverage") or {}).get("value")),
            "liquidation_px": _f(p.get("liquidationPx"), None), "margin_used": _f(p.get("marginUsed")),
            "price_source": "hyperliquid",
        })
    spot_value = 0.0
    for b in spot.get("balances", []):
        coin, total = b.get("coin"), _f(b.get("total"))
        if not coin or total == 0:
            continue
        px = 1.0 if coin in ("USDC", "USDT", "USDH", "USDE") else mids.get(coin, 0.0)
        entry_ntl = _f(b.get("entryNtl"))
        # Unified / portfolio-margin accounts already count stablecoins in perp equity.
        if not (px == 1.0 and config.get("portfolio.hyperliquid_unified", True)):
            spot_value += total * px
        rows.append({
            "ts": now, "account": "hyperliquid", "venue": "hyperliquid", "symbol": coin,
            "asset_class": "cash" if px == 1.0 else "crypto_spot", "qty": total,
            "entry_px": entry_ntl / total if total else None, "price": px, "notional": total * px,
            "unrealized_pnl": total * px - entry_ntl if entry_ntl else None, "leverage": None,
            "liquidation_px": None, "margin_used": None, "price_source": "hyperliquid",
        })

    store.execute("DELETE FROM positions WHERE venue = 'hyperliquid'")
    n = store.insert_df("positions", pd.DataFrame(rows)) if rows else 0

    ms = perp.get("marginSummary", {}) or {}
    perp_equity = _f(ms.get("accountValue"))
    # Portfolio margin and unified accounts report collateral differently; we record both
    # perp equity and spot value and let the risk engine treat the account as one pool.
    store.execute("INSERT INTO account_state VALUES (?, ?, ?, ?, ?, ?, ?, ?)", [
        now, "hyperliquid", "hyperliquid", perp_equity + spot_value,
        _f(perp.get("crossMaintenanceMarginUsed")), _f(ms.get("totalMarginUsed")),
        _f(perp.get("withdrawable")), json.dumps({"perp": perp, "spot": spot}),
    ])
    return n
