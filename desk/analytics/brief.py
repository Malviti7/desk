"""The morning brief: one structured payload that answers
"has anything changed that invalidates what I own?"

Agents get the JSON; `to_markdown` gives a deterministic text version for Telegram or logs.
"""
from __future__ import annotations

from datetime import date, timedelta

from .. import config
from ..store import Store
from . import crypto, regime, risk
from .common import clean, indicator


def overnight(store: Store) -> list[dict]:
    ids = list((config.get("yahoo.futures") or {}).items()) + list((config.get("yahoo.indices") or {}).items())
    out = [indicator(store, f"yf:{t}", n, "") for t, n in ids]
    for coin in config.get("crypto.watch", []):
        out.append(indicator(store, f"hl:{coin}", coin, ""))
    for t in ["^VIX", "DX-Y.NYB", "USDJPY=X", "CL=F", "GC=F"]:
        out.append(indicator(store, f"yf:{t}", None, ""))
    out.append(indicator(store, "fred:DGS10", "10Y Treasury", "%"))
    return [{k: v for k, v in o.items() if k != "spark"} for o in out if o]


def calendar(store: Store, days: int = 7) -> list[dict]:
    end = date.today() + timedelta(days=days)
    return store.records("""SELECT date::VARCHAR AS date, kind, name, detail FROM calendar
                            WHERE date >= current_date AND date <= ? ORDER BY date, kind, name""", [end])


def news(store: Store, limit: int = 40, book_only: bool = False, query: str | None = None) -> list[dict]:
    sql = "SELECT ts::VARCHAR AS ts, source, title, url, tags FROM news WHERE 1=1"
    params: list = []
    if book_only:
        sql += " AND tags LIKE '%$%'"
    if query:
        sql += " AND (lower(title) LIKE ? OR lower(tags) LIKE ?)"
        params += [f"%{query.lower()}%"] * 2
    return store.records(sql + " ORDER BY ts DESC LIMIT ?", params + [limit])


def alerts(store: Store, hours: int = 24) -> list[dict]:
    return store.records(f"""SELECT ts::VARCHAR AS ts, severity, category, message FROM alerts
                             WHERE ts >= now()::TIMESTAMP - INTERVAL {int(hours)} HOUR ORDER BY ts DESC""")


def build(store: Store) -> dict:
    port = risk.portfolio(store)
    rpt = risk.report(store)
    movers = sorted([p for p in port.get("positions", []) if p.get("pnl_1d") is not None],
                    key=lambda p: abs(p["pnl_1d"]), reverse=True)[:5]
    cs = crypto.snapshot(store)
    return clean({
        "date": date.today().isoformat(),
        "regime": regime.regime(store),
        "overnight": overnight(store),
        "book": {
            "pnl_1d": port.get("pnl_1d_total"), "unrealized": port.get("unrealized_total"),
            "exposures": port.get("exposures"), "biggest_movers": movers,
            "hyperliquid": {k: v for k, v in (port.get("hyperliquid") or {}).items() if k != "equity_history"} or None,
            "stops_near": [s for s in rpt.get("stops", []) if s["dist_to_stop_pct"] is not None
                           and s["dist_to_stop_pct"] <= config.get("portfolio.stop_proximity_warn", 0.02) * 100 * 2.5],
            "catalysts": [p for p in port.get("positions", []) if p.get("catalyst_date")],
        },
        "risk": {
            "var_95": (rpt.get("var") or {}).get("var_95"),
            "worst_stress": {k: (rpt.get("worst_stress") or {}).get(k) for k in ("name", "total_pnl", "hyperliquid")},
        },
        "crypto": {
            "oi_weighted_funding_ann": cs.get("oi_weighted_funding_ann"), "crowded": cs.get("crowded"),
            "cross_venue": [{k: v for k, v in x.items() if k != "venues"} for x in cs.get("cross_venue", [])],
            "implied_vol": [{k: v for k, v in i.items() if k != "spark"} for i in cs.get("implied_vol", [])],
            "flows": [{k: v for k, v in i.items() if k != "spark"} for i in cs.get("flows", [])],
        },
        "calendar": calendar(store, 7),
        "news_on_book": news(store, 15, book_only=True),
        "news_macro": news(store, 15),
        "alerts": alerts(store, 24),
        "leaders_in_buy_zone": [{k: l.get(k) for k in ("symbol", "composite", "rs", "pattern", "buy_point",
                                                         "live_price", "dist_to_buy_pct", "held")}
                                for l in _leaders(store) if l.get("zone") == "buy zone"][:10],
        "tradingview_alerts_24h": store.records("""SELECT ts::VARCHAR AS ts, symbol, action, price, message
            FROM tv_alerts WHERE ts >= now()::TIMESTAMP - INTERVAL 24 HOUR ORDER BY ts DESC LIMIT 15"""),
    })


def _leaders(store: Store) -> list[dict]:
    from ..integrations import leaders

    return leaders(store)


def _fmt_money(x) -> str:
    if x is None:
        return "n/a"
    return f"{'-' if x < 0 else ''}${abs(x):,.0f}"


def to_markdown(b: dict) -> str:
    r = b["regime"]
    lines = [f"*Desk morning brief, {b['date']}*", f"Regime: *{r['label']}* ({r['reds']} red, {r['ambers']} amber)"]
    for s in r["signals"]:
        if s["status"] in ("red", "amber"):
            lines.append(f"  {'🔴' if s['status'] == 'red' else '🟠'} {s['name']}: {s['value']}")
    lines.append("\n*Overnight*")
    for o in b["overnight"][:12]:
        chg = o.get("chg_1d")
        unit = "bp" if o.get("chg_unit") == "bp" else "%"
        lines.append(f"  {o['name']}: {o['value']:,.2f} ({chg:+.2f}{unit})" if chg is not None else f"  {o['name']}: {o['value']:,.2f}")
    bk = b["book"]
    lines.append(f"\n*Book*: 1d P&L {_fmt_money(bk.get('pnl_1d'))}, gross {_fmt_money((bk.get('exposures') or {}).get('gross'))}, "
                 f"net {_fmt_money((bk.get('exposures') or {}).get('net'))}")
    for m in bk.get("biggest_movers", []):
        lines.append(f"  {m['symbol']}: {_fmt_money(m['pnl_1d'])}")
    hl = bk.get("hyperliquid")
    if hl:
        lines.append(f"  Hyperliquid headroom {hl.get('headroom_pct', 0):.0f}%, buffer before protected spot {_fmt_money(hl.get('buffer_before_protected'))}")
    ws = b["risk"].get("worst_stress") or {}
    if ws.get("name"):
        lines.append(f"  Worst stress: {ws['name']} {_fmt_money(ws.get('total_pnl'))}")
    if b["alerts"]:
        lines.append("\n*Alerts (24h)*")
        lines += [f"  [{a['severity']}] {a['message']}" for a in b["alerts"][:8]]
    if b["calendar"]:
        lines.append("\n*Next 7 days*")
        lines += [f"  {c['date']} {c['name']} {c['detail'] or ''}".rstrip() for c in b["calendar"][:12]]
    if b.get("leaders_in_buy_zone"):
        lines.append("\n*Leaders in buy zone*")
        lines += [f"  {l['symbol']} {l['dist_to_buy_pct']:+.1f}% from {l['buy_point']:g} (Comp {l['composite'] or 0:.0f}, RS {l['rs'] or 0:.0f})"
                  for l in b["leaders_in_buy_zone"]]
    if b.get("tradingview_alerts_24h"):
        lines.append("\n*TradingView alerts (24h)*")
        lines += [f"  {t['symbol'] or ''} {t['action'] or ''}: {t['message']}" for t in b["tradingview_alerts_24h"][:8]]
    if b["news_on_book"]:
        lines.append("\n*News on your book*")
        lines += [f"  {n['title']} ({n['tags']})" for n in b["news_on_book"][:6]]
    return "\n".join(lines)
