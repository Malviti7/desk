"""TradingView and IBD MarketSurge integrations.

TradingView: alerts arrive by webhook (your Pine Script or price alerts). Charts are embedded
in the dashboard with TradingView's public widget.

MarketSurge: there is no official API. You import ratings from your screens/watchlists as CSV
(or paste them), and set IBD's market outlook. Desk joins ratings with live prices to compute
distance from the buy point and flags names in the buy zone.
"""
from __future__ import annotations

import csv
import io
import json
import re
from datetime import date

import pandas as pd

from . import config
from .analytics.common import clean
from .store import Store, utcnow

# ------------------------------------------------------------------ TradingView webhook
SYMBOL_KEYS = ("symbol", "ticker", "sym")
ACTION_KEYS = ("action", "side", "signal", "order_action")
PRICE_KEYS = ("price", "close", "trigger_price")
MSG_KEYS = ("message", "comment", "text", "note")


def _first(d: dict, keys: tuple[str, ...]):
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return None


def parse_tradingview(body: bytes) -> dict:
    """TradingView sends the alert message verbatim, often without a JSON content type.
    Accept JSON (recommended) or plain text like 'NVDA crossed 140'."""
    text = body.decode("utf-8", errors="replace").strip()
    try:
        data = json.loads(text)
        if not isinstance(data, dict):
            data = {"message": text}
    except json.JSONDecodeError:
        data = {"message": text}
        m = re.match(r"^\s*([A-Z0-9:._!-]{1,20})\b", text)
        if m:
            data["symbol"] = m.group(1)
    sym = _first(data, SYMBOL_KEYS)
    if isinstance(sym, str) and ":" in sym:  # NASDAQ:NVDA -> NVDA
        sym = sym.split(":", 1)[1]
    price = _first(data, PRICE_KEYS)
    try:
        price = float(price) if price is not None else None
    except (TypeError, ValueError):
        price = None
    return {
        "symbol": (sym or "").upper().replace("USDT.P", "").replace("USDT", "") if sym else None,
        "action": str(_first(data, ACTION_KEYS) or "").lower() or None,
        "price": price,
        "interval": str(data.get("interval") or "") or None,
        "message": str(_first(data, MSG_KEYS) or text)[:500],
        "idea": bool(data.get("idea")),
        "raw": data,
    }


def record_tradingview(store: Store, body: bytes) -> dict:
    from . import alerts

    a = parse_tradingview(body)
    now = utcnow()
    store.execute("INSERT INTO tv_alerts VALUES (nextval('tv_seq'), ?, ?, ?, ?, ?, ?, ?)",
                  [now, a["symbol"], a["action"], a["price"], a["interval"], a["message"], json.dumps(a["raw"])])
    tv_id = int(store.query("SELECT max(id) AS id FROM tv_alerts")["id"].iloc[0])
    label = " ".join(x for x in [a["action"] or "", a["symbol"] or "", f"@ {a['price']:g}" if a["price"] else ""] if x)
    msg = f"TradingView: {label}. {a['message']}" if label else f"TradingView: {a['message']}"
    sent = alerts.send(f"📈 *Desk* {msg}")
    store.execute("INSERT INTO alerts VALUES (?, ?, ?, ?, ?, ?)",
                  [f"tv:{tv_id}", now, "medium", "tradingview", msg[:400], sent])
    if a["idea"] and a["symbol"]:
        store.execute("INSERT INTO ideas VALUES (nextval('ideas_seq'), ?, ?, NULL, NULL, ?, 'open', ?, 'tradingview')",
                      [a["symbol"], a["action"] or "watch", a["message"][:300], now])
    return {"ok": True, "id": tv_id, "parsed": {k: v for k, v in a.items() if k != "raw"}}


def tradingview_alerts(store: Store, limit: int = 50) -> list[dict]:
    return store.records("""SELECT id, ts::VARCHAR AS ts, symbol, action, price, interval, message
                            FROM tv_alerts ORDER BY ts DESC LIMIT ?""", [limit])


# ------------------------------------------------------------------ MarketSurge import
# normalized header fragment -> our column. First match wins, so order matters.
MS_COLUMNS = [
    ("symbol", "symbol"), ("ticker", "symbol"),
    ("companyname", "name"), ("name", "name"),
    ("composite", "composite"), ("comprating", "composite"),
    ("eps", "eps_rating"),
    ("rsrating", "rs"), ("relativestrength", "rs"), ("rs", "rs"),
    ("smr", "smr"),
    ("accdis", "acc_dis"), ("ad", "acc_dis"),
    ("groupr", "group_rank"), ("indgroup", "group_rank"), ("industrygroup", "group_rank"),
    ("pivot", "buy_point"), ("buypoint", "buy_point"), ("entry", "buy_point"),
    ("pattern", "pattern"), ("base", "pattern"),
    ("offhigh", "pct_off_high"), ("from52", "pct_off_high"),
    ("price", "price"), ("last", "price"), ("close", "price"),
]
NUMERIC = {"composite", "eps_rating", "rs", "group_rank", "buy_point", "pct_off_high", "price"}


def _norm(h: str) -> str:
    return re.sub(r"[^a-z0-9]", "", h.lower())


def _map_headers(headers: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for h in headers:
        n = _norm(h)
        for frag, col in MS_COLUMNS:
            if col in out.values():
                continue
            if (n == frag) or (len(frag) > 3 and frag in n):
                out[h] = col
                break
    return out


def _num(x) -> float | None:
    if x is None:
        return None
    s = re.sub(r"[^\d.\-]", "", str(x))
    try:
        return float(s) if s not in ("", "-", ".") else None
    except ValueError:
        return None


def import_marketsurge(store: Store, text: str, list_name: str = "import") -> dict:
    """Import a MarketSurge screen or watchlist (CSV, or tab-separated paste from a table)."""
    text = text.strip().lstrip("﻿")
    if not text:
        return {"ok": False, "error": "empty"}
    dialect = "excel-tab" if text.split("\n", 1)[0].count("\t") > text.split("\n", 1)[0].count(",") else "excel"
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    mapping = _map_headers(reader.fieldnames or [])
    if "symbol" not in mapping.values():
        return {"ok": False, "error": "No Symbol column found", "headers": reader.fieldnames}
    today = date.today()
    rows = []
    for r in reader:
        rec = {col: r.get(h) for h, col in mapping.items()}
        sym = (rec.get("symbol") or "").strip().upper()
        if not sym or not re.match(r"^[A-Z0-9.\-]{1,10}$", sym):
            continue
        for k in NUMERIC:
            if k in rec:
                rec[k] = _num(rec[k])
        rows.append({
            "symbol": sym, "as_of": today, "list_name": list_name, "name": rec.get("name"),
            "composite": rec.get("composite"), "eps_rating": rec.get("eps_rating"), "rs": rec.get("rs"),
            "smr": (rec.get("smr") or None), "acc_dis": (rec.get("acc_dis") or None),
            "group_rank": rec.get("group_rank"), "pattern": (rec.get("pattern") or None),
            "buy_point": rec.get("buy_point"), "pct_off_high": rec.get("pct_off_high"),
            "price": rec.get("price"), "raw": json.dumps(r),
        })
    if not rows:
        return {"ok": False, "error": "No rows with valid symbols"}
    df = pd.DataFrame(rows).drop_duplicates("symbol", keep="last")
    store.insert_df("ms_ratings", df, replace_keys=["symbol", "as_of"])
    return {"ok": True, "rows": len(df), "columns_mapped": mapping}


# ------------------------------------------------------------------ IBD market outlook
OUTLOOKS = {
    "confirmed_uptrend": ("Confirmed uptrend", "green"),
    "uptrend_under_pressure": ("Uptrend under pressure", "amber"),
    "rally_attempt": ("Rally attempt", "amber"),
    "market_in_correction": ("Market in correction", "red"),
}


def set_outlook(store: Store, status: str, exposure_pct: float | None = None, note: str = "",
                set_by: str = "user") -> dict:
    key = re.sub(r"[^a-z]+", "_", status.lower()).strip("_")
    if key not in OUTLOOKS:
        return {"ok": False, "error": f"status must be one of {list(OUTLOOKS)}"}
    store.execute("INSERT INTO ms_outlook VALUES (?, ?, ?, ?, ?)", [utcnow(), key, exposure_pct, note, set_by])
    return {"ok": True}


def outlook(store: Store) -> dict | None:
    r = store.records("SELECT ts::VARCHAR AS ts, status, exposure_pct, note, set_by FROM ms_outlook ORDER BY ts DESC LIMIT 1")
    if not r:
        return None
    o = r[0]
    o["label"], o["color"] = OUTLOOKS.get(o["status"], (o["status"], "na"))
    return o


# ------------------------------------------------------------------ leaders
def leaders(store: Store) -> list[dict]:
    from .analytics.risk import price_series

    df = store.query("""SELECT * EXCLUDE (raw) FROM ms_ratings
                        WHERE as_of = (SELECT max(as_of) FROM ms_ratings r2 WHERE r2.symbol = ms_ratings.symbol)""")
    if df.empty:
        return []
    zone = float(config.get("marketsurge.buy_zone_pct", 5.0))
    held = set(store.query("SELECT DISTINCT symbol FROM positions").get("symbol", []))
    out = []
    for r in df.to_dict("records"):
        s = price_series(store, r["symbol"], False)
        live = float(s.iloc[-1]) if not s.empty else r.get("price")
        ma50 = float(s.iloc[-50:].mean()) if len(s) >= 50 else None
        bp = r.get("buy_point")
        dist = (live / bp - 1) * 100 if (live and bp) else None
        status = None
        if dist is not None:
            status = "buy zone" if 0 <= dist <= zone else "extended" if dist > zone else "below pivot"
        out.append({**r, "as_of": str(r["as_of"]), "live_price": live, "dist_to_buy_pct": dist,
                    "zone": status, "vs_50d": (live / ma50 - 1) * 100 if (live and ma50) else None,
                    "held": r["symbol"] in held})
    out.sort(key=lambda x: (-(x.get("composite") or 0), -(x.get("rs") or 0)))
    return clean(out)


def chart_config(store: Store) -> dict:
    tv = config.get("tradingview", {}) or {}
    held = store.records("""SELECT symbol, bool_or(asset_class LIKE 'crypto%') AS crypto FROM positions
                            WHERE asset_class <> 'cash' GROUP BY symbol ORDER BY symbol""")
    lead = [r["symbol"] for r in leaders(store)]
    return {
        "crypto_template": tv.get("crypto_template", "BINANCE:{coin}USDT"),
        "overrides": tv.get("symbol_overrides", {}) or {},
        "default_interval": tv.get("default_interval", "D"),
        "studies": tv.get("studies", []),
        "marketsurge_url": config.get("marketsurge.chart_url", "https://marketsurge.investors.com/"),
        "tradingview_url": tv.get("chart_url", "https://www.tradingview.com/chart/?symbol={tv_symbol}"),
        "groups": {
            "Positions": [{"symbol": r["symbol"], "crypto": bool(r["crypto"])} for r in held],
            "Leaders": [{"symbol": s, "crypto": False} for s in lead],
            "Watchlist": [{"symbol": s, "crypto": False} for s in config.get("equities.watchlist", [])],
            "Crypto": [{"symbol": s, "crypto": True} for s in config.get("crypto.watch", [])],
            "Macro": [{"symbol": s, "crypto": False} for s in tv.get("macro_symbols", [])],
        },
    }
