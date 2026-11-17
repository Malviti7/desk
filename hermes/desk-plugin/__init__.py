"""Hermes plugin for Desk.

Registers Desk's tools natively in Hermes (no MCP setup needed) plus the bundled skills.
Every tool is a thin HTTP call to a running Desk server, so the server stays the single
owner of the data. Standard library only, so it adds no dependencies to Hermes.

Environment (optional):
  DESK_URL        default http://127.0.0.1:8765
  DESK_API_TOKEN  only if you set one on the Desk server
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

TOOLSET = "desk"
HERE = Path(__file__).resolve().parent

STRIP_KEYS = {"spark", "pnl_history", "equity_history"}  # UI-only fields, save agent context


def _base() -> str:
    return os.environ.get("DESK_URL", "http://127.0.0.1:8765").rstrip("/")


def _strip(x):
    if isinstance(x, dict):
        return {k: _strip(v) for k, v in x.items() if k not in STRIP_KEYS}
    if isinstance(x, list):
        return [_strip(v) for v in x]
    return x


def _call(method: str, path: str, query: dict | None = None, body: dict | None = None) -> str:
    q = {k: v for k, v in (query or {}).items() if v is not None and v != ""}
    url = f"{_base()}{path}" + (f"?{urllib.parse.urlencode(q)}" if q else "")
    headers = {"Content-Type": "application/json"}
    token = os.environ.get("DESK_API_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            raw = r.read().decode()
            if "json" not in (r.headers.get("Content-Type") or ""):
                return raw
            return json.dumps(_strip(json.loads(raw)), separators=(",", ":"), default=str)
    except urllib.error.HTTPError as e:
        return json.dumps({"success": False, "error": f"HTTP {e.code}: {e.read().decode()[:300]}"})
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        return json.dumps({"success": False, "error": f"Desk server not reachable at {_base()} ({e}). "
                                                      "Start it with `desk serve` or set DESK_URL."})


def _s(desc: str, props: dict | None = None, required: list[str] | None = None) -> dict:
    return {"description": desc,
            "parameters": {"type": "object", "properties": props or {}, "required": required or []}}


STR = {"type": "string"}
NUM = {"type": "number"}
INT = {"type": "integer"}
BOOL = {"type": "boolean"}

# name -> (schema, handler(params) -> str)
TOOLS = {
    "desk_morning_brief": (
        _s("Full morning brief: regime signals (incl. IBD outlook), overnight moves, book P&L and exposures, "
           "Hyperliquid margin and buffer before protected spot, worst stress, cross-venue crypto crowding, "
           "leaders in buy zone, TradingView alerts, 7-day calendar, news on positions, alerts. "
           "format: 'json' (default) or 'markdown'.", {"format": {**STR, "enum": ["json", "markdown"]}}),
        lambda p: _call("GET", "/api/brief.md" if p.get("format") == "markdown" else "/api/brief")),
    "desk_regime": (
        _s("Regime check: label (Risk-on/Neutral/Caution/Stress) and each signal with status, value and why."),
        lambda p: _call("GET", "/api/regime")),
    "desk_macro": (
        _s("Cross-asset macro dashboard: rates (changes in bp), liquidity, credit, FX, vol, commodities, "
           "futures, indices, economy, correlations, Treasury curve."),
        lambda p: _call("GET", "/api/macro")),
    "desk_crypto": (
        _s("Crypto snapshot: Hyperliquid perps (funding, OI, crowding), cross-venue view, DVOL, stablecoin "
           "supply, TVL, crypto equities, trend vs 20/50/200d."),
        lambda p: _call("GET", "/api/crypto")),
    "desk_cross_venue": (
        _s("Coinalyze cross-exchange view: total OI and 24h change, OI-weighted funding (ann %), venue funding "
           "spread, 24h long/short liquidations, crowding, Hyperliquid share, per-venue breakdown.",
           {"coin": {**STR, "description": "e.g. BTC. Omit for all tracked coins."}}),
        lambda p: _call("GET", "/api/crypto/venues", {"coin": p.get("coin")})),
    "desk_funding_history": (
        _s("Hourly Hyperliquid funding (ann %), OI and mark history for one coin.",
           {"coin": STR, "days": INT}, ["coin"]),
        lambda p: _call("GET", f"/api/crypto/funding/{urllib.parse.quote(str(p['coin']).upper())}",
                        {"days": p.get("days", 14)})),
    "desk_positioning": (
        _s("Equities and positioning: sector/factor/index performance, CFTC COT with 3y percentiles, "
           "short interest, 13F crowding."),
        lambda p: _call("GET", "/api/equities")),
    "desk_leaders": (
        _s("IBD MarketSurge leaders the user imported: Composite, EPS, RS, SMR, A/D, group rank, base, buy point, "
           "live price, distance from buy point, zone (buy zone / extended / below pivot)."),
        lambda p: _call("GET", "/api/leaders")),
    "desk_portfolio": (
        _s("All positions across accounts with notional, P&L, betas, days to exit, thesis, stop/target "
           "distance; exposures; Hyperliquid headroom, protected spot value, buffer before protected spot."),
        lambda p: _call("GET", "/api/portfolio")),
    "desk_risk_report": (
        _s("Risk report: exposures, factor exposures, VaR/ES, all stress scenarios with Hyperliquid margin "
           "impact, liquidity, correlations, stops."),
        lambda p: _call("GET", "/api/risk")),
    "desk_stress_test": (
        _s("Shock the book. spx_pct/btc_pct are decimals (-0.10 = -10%) applied via beta. overrides sets a direct "
           "move per symbol, e.g. {\"HYPE\": -0.4}. add_positions tests a trade first: "
           "[{\"symbol\":\"SOL\",\"notional\":-50000,\"asset_class\":\"crypto_perp\"}] (negative = short). "
           "Returns P&L by position and whether protected spot would be at risk.",
           {"spx_pct": NUM, "btc_pct": NUM, "overrides": {"type": "object"},
            "add_positions": {"type": "array", "items": {"type": "object"}}, "name": STR}),
        lambda p: _call("POST", "/api/stress", body={
            "name": p.get("name", "custom"), "spx": p.get("spx_pct", 0.0), "btc": p.get("btc_pct", 0.0),
            "overrides": p.get("overrides") or {}, "add": p.get("add_positions") or []})),
    "desk_news": (
        _s("Recent headlines tagged to held symbols ($BTC) and macro themes. book_only=true for only "
           "headlines touching positions.", {"query": STR, "book_only": BOOL, "limit": INT}),
        lambda p: _call("GET", "/api/news", {"q": p.get("query"), "book_only": str(bool(p.get("book_only"))).lower(),
                                             "limit": p.get("limit", 30)})),
    "desk_calendar": (
        _s("Upcoming macro releases, FOMC, earnings for held/large-cap names, manual events.", {"days": INT}),
        lambda p: _call("GET", "/api/calendar", {"days": p.get("days", 14)})),
    "desk_alerts": (
        _s("Alerts fired recently (regime, funding, stops, margin, liquidation distance, protected spot, "
           "ideas, leaders, TradingView).", {"hours": INT}),
        lambda p: _call("GET", "/api/alerts", {"hours": p.get("hours", 72)})),
    "desk_tradingview_alerts": (
        _s("Alerts the user's TradingView charts sent to Desk by webhook.", {"limit": INT}),
        lambda p: _call("GET", "/api/tradingview/alerts", {"limit": p.get("limit", 30)})),
    "desk_list_series": (
        _s("Catalog of stored time series (ids like fred:DGS10, yf:^VIX, hl:BTC, cz:BTC:funding_ann).",
           {"query": STR}),
        lambda p: _call("GET", "/api/series", {"q": p.get("query")})),
    "desk_series": (
        _s("Daily history and stats for one series id.", {"series_id": STR, "days": INT}, ["series_id"]),
        lambda p: _call("GET", f"/api/series/{urllib.parse.quote(str(p['series_id']), safe=':^.=-')}",
                        {"days": p.get("days", 365)})),
    "desk_set_thesis": (
        _s("Record or update a position's thesis, stop, target, catalyst and catalyst date (YYYY-MM-DD).",
           {"symbol": STR, "thesis": STR, "direction": {**STR, "enum": ["long", "short"]}, "stop": NUM,
            "target": NUM, "catalyst": STR, "catalyst_date": STR}, ["symbol", "thesis"]),
        lambda p: _call("PUT", "/api/theses", body={**{k: p.get(k) for k in (
            "symbol", "thesis", "stop", "target", "catalyst", "catalyst_date")},
            "direction": p.get("direction", "long"), "updated_by": "hermes"})),
    "desk_add_idea": (
        _s("Add a trade idea. If trigger_px is set, an alert fires when price goes trigger_dir ('above'/'below') it.",
           {"symbol": STR, "direction": STR, "note": STR, "trigger_px": NUM,
            "trigger_dir": {**STR, "enum": ["above", "below"]}}, ["symbol", "direction", "note"]),
        lambda p: _call("POST", "/api/ideas", body={**{k: p.get(k) for k in (
            "symbol", "direction", "note", "trigger_px")}, "trigger_dir": p.get("trigger_dir", "below"),
            "created_by": "hermes"})),
    "desk_list_ideas": (
        _s("Ideas pipeline. status: open, triggered, closed, or omit for all.", {"status": STR}),
        lambda p: _call("GET", "/api/ideas", {"status": p.get("status")})),
    "desk_set_market_outlook": (
        _s("Record IBD's market outlook as the user reports it. It becomes the first regime signal.",
           {"status": {**STR, "enum": ["confirmed_uptrend", "uptrend_under_pressure", "rally_attempt",
                                       "market_in_correction"]}, "exposure_pct": NUM, "note": STR}, ["status"]),
        lambda p: _call("PUT", "/api/marketsurge/outlook", body={
            "status": p["status"], "exposure_pct": p.get("exposure_pct"), "note": p.get("note", ""), "set_by": "hermes"})),
    "desk_import_marketsurge": (
        _s("Import MarketSurge ratings from CSV or tab-separated text the user pasted (needs a Symbol column).",
           {"csv_text": STR, "list_name": STR}, ["csv_text"]),
        lambda p: _call("POST", "/api/marketsurge/import", body={
            "csv": p["csv_text"], "list_name": p.get("list_name", "hermes-import")})),
    "desk_notify": (
        _s("Send the user a message through the Desk Telegram bot (if configured).", {"text": STR}, ["text"]),
        lambda p: _call("POST", "/api/notify", body={"text": p["text"]})),
    "desk_refresh_data": (
        _s("Re-run data ingestion now. job: 'all' or a job name from desk_data_status.", {"job": STR}),
        lambda p: _call("POST", f"/api/ingest/{urllib.parse.quote(p.get('job') or 'all')}")),
    "desk_data_status": (
        _s("When each data job last ran, whether it succeeded, and why it was skipped."),
        lambda p: _call("GET", "/api/ingest/status")),
}


def _make_handler(fn):
    def handler(params=None, **kwargs):
        try:
            return fn(params or {})
        except KeyError as e:
            return json.dumps({"success": False, "error": f"missing parameter {e}"})
        except Exception as e:  # noqa: BLE001  never crash the agent loop
            return json.dumps({"success": False, "error": str(e)})
    return handler


def register(ctx):
    for name, (schema, fn) in TOOLS.items():
        ctx.register_tool(name=name, toolset=TOOLSET, schema={"name": name, **schema}, handler=_make_handler(fn))

    skills_dir = HERE / "skills"
    if skills_dir.is_dir():
        for skill in sorted(skills_dir.iterdir()):
            md = skill / "SKILL.md"
            if md.is_file():
                ctx.register_skill(skill.name, md)

    if hasattr(ctx, "register_command"):
        ctx.register_command(
            "desk",
            lambda *a, **k: _call("GET", "/api/brief.md"),
            description="Show the Desk morning brief",
        )
