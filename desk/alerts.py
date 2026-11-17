"""Alert rules. Evaluated on a schedule; each alert fires once per key per day.
Delivered to the dashboard, to agents via the API/MCP, and to Telegram if configured."""
from __future__ import annotations

from datetime import date

import httpx

from . import config
from .analytics import crypto, regime, risk
from .store import Store, utcnow


def _telegram(text: str) -> bool:
    token, chat = config.env("TELEGRAM_BOT_TOKEN"), config.env("TELEGRAM_CHAT_ID")
    if not (token and chat and config.get("alerts.telegram", True)):
        return False
    try:
        httpx.post(f"https://api.telegram.org/bot{token}/sendMessage",
                   json={"chat_id": chat, "text": text, "parse_mode": "Markdown"}, timeout=10)
        return True
    except Exception:  # noqa: BLE001
        return False


def send(text: str) -> bool:
    return _telegram(text)


def evaluate(store: Store) -> list[dict]:
    """Return current alert conditions as dicts with key/severity/category/message."""
    out: list[dict] = []
    today = date.today().isoformat()

    for s in regime.regime(store)["signals"]:
        if s["status"] == "red":
            out.append({"key": f"regime:{s['name']}:{today}", "severity": "high", "category": "macro",
                        "message": f"{s['name']}: {s['value']}. {s['why']}"})

    held = {p["coin"]: p for p in crypto.perps(store) if p["held"]}
    for coin, p in held.items():
        if p["crowding"]:
            out.append({"key": f"funding:{coin}:{today}", "severity": "medium", "category": "crypto",
                        "message": f"{coin} funding {p['funding_ann']:+.0f}% annualized ({p['crowding']}) on a coin you hold."})

    held_coins = set(store.query("SELECT DISTINCT symbol FROM positions WHERE asset_class LIKE 'crypto%'").get("symbol", []))
    for x in crypto.cross_venue(store):
        if x["coin"] in held_coins and x["crowding"]:
            out.append({"key": f"xfunding:{x['coin']}:{today}", "severity": "medium", "category": "crypto",
                        "message": f"{x['coin']} OI-weighted funding across venues {x['funding_ann_oiw']:+.0f}% annualized "
                                   f"({x['crowding']}), OI ${x['oi_usd'] / 1e9:.2f}B."})

    port = risk.portfolio(store)
    pw = config.get("portfolio", {}) or {}
    for pos in port.get("positions", []):
        d = pos.get("dist_to_stop_pct")
        if pos.get("stop_breached"):
            out.append({"key": f"stop:{pos['symbol']}:{today}", "severity": "high", "category": "portfolio",
                        "message": f"{pos['symbol']} through its stop ({pos['price']:.4g} vs stop {pos['stop']:.4g})."})
        elif d is not None and d <= pw.get("stop_proximity_warn", 0.02) * 100:
            out.append({"key": f"stopnear:{pos['symbol']}:{today}", "severity": "medium", "category": "portfolio",
                        "message": f"{pos['symbol']} within {d:.1f}% of stop {pos['stop']:.4g}."})

    hl = port.get("hyperliquid")
    if hl:
        if hl.get("headroom_pct") is not None and hl["headroom_pct"] < pw.get("margin_headroom_warn", 0.3) * 100:
            out.append({"key": f"headroom:{today}", "severity": "high", "category": "margin",
                        "message": f"Hyperliquid margin headroom {hl['headroom_pct']:.0f}%."})
        if hl.get("protected_spot_value") and hl.get("buffer_before_protected", 1) < 0:
            out.append({"key": f"protected:{today}", "severity": "critical", "category": "margin",
                        "message": "Perp risk is now drawing on your protected spot collateral "
                                   f"(buffer {hl['buffer_before_protected']:,.0f})."})
        for l in hl.get("liquidation_distances", []):
            if l["distance_pct"] < pw.get("liq_distance_warn", 0.15) * 100:
                out.append({"key": f"liq:{l['symbol']}:{today}", "severity": "high", "category": "margin",
                            "message": f"{l['symbol']} is {l['distance_pct']:.1f}% from liquidation ({l['liquidation_px']:.4g})."})

    from .integrations import leaders

    min_comp = float(config.get("marketsurge.leader_min_composite", 90))
    for l in leaders(store):
        if l.get("zone") == "buy zone" and (l.get("composite") or 0) >= min_comp and not l.get("held"):
            out.append({"key": f"buyzone:{l['symbol']}:{today}", "severity": "medium", "category": "leaders",
                        "message": f"{l['symbol']} in buy zone: {l['dist_to_buy_pct']:+.1f}% from {l['buy_point']:g} "
                                   f"(Comp {l['composite']:.0f}, RS {l.get('rs') or 0:.0f}, {l.get('pattern') or 'base n/a'})."})

    for idea in store.records("SELECT * FROM ideas WHERE status = 'open' AND trigger_px IS NOT NULL"):
        px = risk.price_series(store, idea["symbol"], True)
        if px.empty:
            px = risk.price_series(store, idea["symbol"], False)
        if px.empty:
            continue
        last = float(px.iloc[-1])
        hit = last >= idea["trigger_px"] if idea["trigger_dir"] == "above" else last <= idea["trigger_px"]
        if hit:
            out.append({"key": f"idea:{idea['id']}", "idea_id": idea["id"], "severity": "medium", "category": "ideas",
                        "message": f"Idea triggered: {idea['direction']} {idea['symbol']} at {last:.4g} "
                                   f"({idea['trigger_dir']} {idea['trigger_px']:.4g}). {idea.get('note') or ''}"})
    return out


def run(store: Store) -> int:
    fired = 0
    existing = set(store.query("SELECT key FROM alerts").get("key", []))
    for a in evaluate(store):
        if a["key"] in existing:
            continue
        icon = {"critical": "🚨", "high": "🔴", "medium": "🟠"}.get(a["severity"], "")
        sent = _telegram(f"{icon} *Desk* [{a['category']}] {a['message']}")
        store.execute("INSERT INTO alerts VALUES (?, ?, ?, ?, ?, ?)",
                      [a["key"], utcnow(), a["severity"], a["category"], a["message"], sent])
        if a.get("idea_id") is not None:
            store.execute("UPDATE ideas SET status = 'triggered' WHERE id = ?", [a["idea_id"]])
        fired += 1
    return fired
