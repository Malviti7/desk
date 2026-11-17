"""Account connectors beyond Hyperliquid: Coinbase (read-only key) and a manual CSV."""
from __future__ import annotations

import pandas as pd

from .. import config
from ..store import Store, utcnow

STABLES = {"USD", "USDC", "USDT", "DAI", "PYUSD"}


def _price(store: Store, symbol: str, source: str) -> float | None:
    """Latest price from stored series: Hyperliquid first for crypto, Yahoo otherwise."""
    order = [f"hl:{symbol}", f"yf:{symbol}-USD", f"yf:{symbol}"] if source != "yahoo" else [f"yf:{symbol}", f"hl:{symbol}"]
    snap = store.query("""SELECT mark FROM perp_snapshots WHERE coin = ?
                          ORDER BY ts DESC LIMIT 1""", [symbol]) if source != "yahoo" else pd.DataFrame()
    if not snap.empty:
        return float(snap["mark"].iloc[0])
    for sid in order:
        s = store.series(sid, days=10)
        if not s.empty:
            return float(s.iloc[-1])
    return None


def run_coinbase(store: Store) -> int:
    key, secret = config.env("COINBASE_API_KEY"), config.env("COINBASE_API_SECRET")
    if not key or not secret:
        raise RuntimeError("COINBASE_API_KEY / COINBASE_API_SECRET not set")
    try:
        from coinbase.rest import RESTClient
    except ImportError as e:
        raise RuntimeError("pip install 'desk[coinbase]'") from e
    client = RESTClient(api_key=key, api_secret=secret.replace("\\n", "\n"))
    now, rows, cursor = utcnow(), [], None
    while True:
        resp = client.get_accounts(limit=250, cursor=cursor) if cursor else client.get_accounts(limit=250)
        data = resp.to_dict() if hasattr(resp, "to_dict") else resp
        for a in data.get("accounts", []):
            ccy = a.get("currency")
            qty = float((a.get("available_balance") or {}).get("value", 0)) + float((a.get("hold") or {}).get("value", 0))
            if qty <= 0:
                continue
            px = 1.0 if ccy in STABLES else _price(store, ccy, "crypto")
            rows.append({"ts": now, "account": "coinbase", "venue": "coinbase", "symbol": ccy,
                         "asset_class": "cash" if ccy in STABLES else "crypto_spot", "qty": qty,
                         "entry_px": None, "price": px, "notional": qty * px if px else None,
                         "unrealized_pnl": None, "leverage": None, "liquidation_px": None,
                         "margin_used": None, "price_source": "hyperliquid"})
        if not data.get("has_next"):
            break
        cursor = data.get("cursor")
    store.execute("DELETE FROM positions WHERE venue = 'coinbase'")
    return store.insert_df("positions", pd.DataFrame(rows)) if rows else 0


def run_manual(store: Store) -> int:
    path = config.resolve(config.get("portfolio.manual_csv", "config/positions.csv"))
    if not path.exists():
        store.execute("DELETE FROM positions WHERE venue = 'manual'")
        return 0
    df = pd.read_csv(path)
    now, rows = utcnow(), []
    for r in df.to_dict("records"):
        sym, src = str(r["symbol"]).upper(), str(r.get("price_source") or "yahoo")
        qty = float(r["qty"])
        px = 1.0 if sym in STABLES else _price(store, sym, src)
        entry = float(r["entry_px"]) if pd.notna(r.get("entry_px")) else None
        rows.append({"ts": now, "account": str(r.get("account") or "manual"), "venue": "manual",
                     "symbol": sym, "asset_class": r.get("asset_class", "equity"), "qty": qty,
                     "entry_px": entry, "price": px, "notional": qty * px if px else None,
                     "unrealized_pnl": (px - entry) * qty if (px and entry) else None,
                     "leverage": None, "liquidation_px": None, "margin_used": None, "price_source": src})
    store.execute("DELETE FROM positions WHERE venue = 'manual'")
    return store.insert_df("positions", pd.DataFrame(rows)) if rows else 0
