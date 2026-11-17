"""MCP server for your agents (Hermes, Claude, anything that speaks MCP).

It is a thin client over the Desk REST API, so the API process stays the single owner of
the database. Start the API first (`desk serve`), then point your agent at this server:

    hermes mcp add desk --command "desk mcp"          # stdio
    desk mcp --http --port 8766                       # or streamable HTTP for remote agents

Tools are read-mostly. Agents can write theses, ideas, and notifications, and can trigger a
data refresh. There are deliberately no order-execution tools here.
"""
from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from . import config

try:  # mcp >= 2
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server  # type: ignore

INSTRUCTIONS = """Desk is the user's personal trading desk: macro regime, cross-asset data, crypto
derivatives, positioning, news, and their live portfolio and risk across Hyperliquid, Coinbase,
and manual accounts. Start a morning with get_morning_brief. Before suggesting any trade, call
get_risk_report and run_stress_test with the proposed change in mind. The user's protected spot
(see portfolio.protected_spot) must never be put at risk by perp positions: check
buffer_before_protected. Percent changes for rates are in basis points (chg_unit)."""

logging.getLogger("httpx").setLevel(logging.WARNING)

mcp = _Server("desk", instructions=INSTRUCTIONS)


def _base() -> str:
    return config.env("DESK_URL", "http://127.0.0.1:8765").rstrip("/")


def _headers() -> dict:
    t = config.env("DESK_API_TOKEN")
    return {"Authorization": f"Bearer {t}"} if t else {}


def _call(method: str, path: str, **kw) -> Any:
    try:
        r = httpx.request(method, f"{_base()}{path}", headers=_headers(), timeout=120, **kw)
        r.raise_for_status()
        return r.json() if "json" in r.headers.get("content-type", "") else r.text
    except httpx.ConnectError:
        return {"error": f"Desk API not reachable at {_base()}. Start it with `desk serve`."}
    except httpx.HTTPStatusError as e:
        return {"error": f"{e.response.status_code}: {e.response.text[:300]}"}


def _out(x: Any) -> str:
    return x if isinstance(x, str) else json.dumps(x, separators=(",", ":"), default=str)


def _strip_sparks(x: Any) -> Any:
    """Sparklines are for the UI; drop them to save agent context."""
    if isinstance(x, dict):
        return {k: _strip_sparks(v) for k, v in x.items() if k not in ("spark", "pnl_history", "equity_history")}
    if isinstance(x, list):
        return [_strip_sparks(v) for v in x]
    return x


# ------------------------------------------------------------------ morning + regime
@mcp.tool()
def get_morning_brief(format: str = "json") -> str:
    """The full morning brief: regime signals, overnight moves, book P&L and exposures, Hyperliquid
    margin and protected-spot buffer, worst stress case, crypto crowding, 7-day calendar, news tagged
    to positions, and alerts from the last 24h. format: 'json' (default) or 'markdown'."""
    if format == "markdown":
        return _out(_call("GET", "/api/brief.md"))
    return _out(_strip_sparks(_call("GET", "/api/brief")))


@mcp.tool()
def get_regime() -> str:
    """Regime check: label (Risk-on / Neutral / Caution / Stress) plus each signal with status
    (green/amber/red), value, and why it matters. VIX term structure, credit, yen carry, dollar,
    MOVE, stock/bond correlation, net liquidity, Fed path proxy, NFCI, BTC implied vol."""
    return _out(_call("GET", "/api/regime"))


@mcp.tool()
def get_macro_snapshot() -> str:
    """Cross-asset macro dashboard grouped by rates, liquidity, credit, fx, vol, commodities,
    futures, indices, economy, correlations, and the yield curve. Each item has value, 1d/1w/1m
    change, 1y percentile and z-score."""
    return _out(_strip_sparks(_call("GET", "/api/macro")))


# ------------------------------------------------------------------ crypto + positioning
@mcp.tool()
def get_crypto_snapshot() -> str:
    """Hyperliquid perps (funding annualized, OI and 24h OI change, premium, crowding flags),
    OI-weighted funding, BTC/ETH implied vol (DVOL), stablecoin supply, DeFi TVL, crypto equities,
    and trend vs 20/50/200 day averages for watched coins."""
    return _out(_strip_sparks(_call("GET", "/api/crypto")))


@mcp.tool()
def get_funding_history(coin: str, days: int = 14) -> str:
    """Hourly funding (annualized %), open interest, and mark price history for one perp."""
    return _out(_call("GET", f"/api/crypto/funding/{coin}", params={"days": days}))


@mcp.tool()
def get_positioning() -> str:
    """Equities and positioning: sector and factor performance, CFTC COT net speculative positioning
    with 3y percentiles, short interest and days to cover, and 13F crowding across tracked funds."""
    return _out(_call("GET", "/api/equities"))


# ------------------------------------------------------------------ portfolio + risk
@mcp.tool()
def get_portfolio() -> str:
    """All positions across accounts with price, notional, % of gross, unrealized and 1d P&L, betas,
    days to exit, thesis, stop/target distances, plus exposures and Hyperliquid account state
    (headroom, protected spot value, buffer before protected spot, liquidation distances)."""
    return _out(_strip_sparks(_call("GET", "/api/portfolio")))


@mcp.tool()
def get_risk_report() -> str:
    """Risk report: exposures (gross, net, beta-adjusted to SPX and BTC, concentration), factor
    exposures, historical VaR and expected shortfall, all configured stress scenarios with
    Hyperliquid margin impact, liquidity (days to exit), correlations, and stop distances."""
    return _out(_strip_sparks(_call("GET", "/api/risk")))


@mcp.tool()
def run_stress_test(spx_pct: float = 0.0, btc_pct: float = 0.0, overrides: dict[str, float] | None = None,
                    add_positions: list[dict] | None = None, name: str = "custom") -> str:
    """Shock the current book. spx_pct and btc_pct are decimal moves (e.g. -0.10 for -10%) applied via
    each position's beta; overrides set a direct decimal move per symbol, e.g. {"HYPE": -0.4}.
    Returns P&L by position and, for Hyperliquid, equity and maintenance margin after the shock and
    whether protected spot would be at risk.
    add_positions tests a trade before you make it: [{"symbol": "SOL", "notional": -50000,
    "asset_class": "crypto_perp"}] (negative notional = short). Run with zero shocks to see the
    new margin state, and with btc_pct=-0.25 to see the downside."""
    return _out(_call("POST", "/api/stress", json={"name": name, "spx": spx_pct, "btc": btc_pct,
                                                   "overrides": overrides or {}, "add": add_positions or []}))


# ------------------------------------------------------------------ news, calendar, data
@mcp.tool()
def get_news(query: str | None = None, book_only: bool = False, limit: int = 30) -> str:
    """Recent headlines from central banks, SEC, crypto outlets, and Google News. Tags mark held
    symbols ($BTC) and macro themes (fed, rates, inflation, japan, geopolitics, crypto-reg).
    book_only=True returns only headlines that mention something you hold."""
    return _out(_call("GET", "/api/news", params={"q": query, "book_only": book_only, "limit": limit}))


@mcp.tool()
def get_calendar(days: int = 14) -> str:
    """Upcoming macro releases, FOMC, earnings for held and large-cap names, and manual events."""
    return _out(_call("GET", "/api/calendar", params={"days": days}))


@mcp.tool()
def get_alerts(hours: int = 72) -> str:
    """Alerts fired recently: regime reds, crowded funding on held coins, stops, margin, liquidation
    distance, protected spot, and triggered ideas."""
    return _out(_call("GET", "/api/alerts", params={"hours": hours}))


@mcp.tool()
def list_series(query: str | None = None) -> str:
    """Catalog of every stored time series (id, name, category, unit, last date). Ids look like
    fred:DGS10, yf:^VIX, hl:BTC, deribit:DVOL:BTC, llama:stablecoin_supply."""
    return _out(_call("GET", "/api/series", params={"q": query}))


@mcp.tool()
def get_series(series_id: str, days: int = 365) -> str:
    """Daily history for one series plus summary stats (changes, percentile, z-score)."""
    return _out(_call("GET", f"/api/series/{series_id}", params={"days": days}))


# ------------------------------------------------------------------ writes (notes only)
@mcp.tool()
def set_thesis(symbol: str, thesis: str, direction: str = "long", stop: float | None = None,
               target: float | None = None, catalyst: str | None = None, catalyst_date: str | None = None,
               agent: str = "hermes") -> str:
    """Record or update the thesis for a position: direction, why, stop, target, catalyst and date
    (YYYY-MM-DD). Stops and targets drive the stop-distance alerts."""
    return _out(_call("PUT", "/api/theses", json={
        "symbol": symbol, "direction": direction, "thesis": thesis, "stop": stop, "target": target,
        "catalyst": catalyst, "catalyst_date": catalyst_date, "updated_by": agent}))


@mcp.tool()
def add_idea(symbol: str, direction: str, note: str, trigger_px: float | None = None,
             trigger_dir: str = "below", agent: str = "hermes") -> str:
    """Add a trade idea to the pipeline. If trigger_px is set, an alert fires when price goes
    'above' or 'below' it (trigger_dir)."""
    return _out(_call("POST", "/api/ideas", json={"symbol": symbol, "direction": direction, "note": note,
                                                  "trigger_px": trigger_px, "trigger_dir": trigger_dir,
                                                  "created_by": agent}))


@mcp.tool()
def list_ideas(status: str | None = "open") -> str:
    """Ideas pipeline. status: open, triggered, closed, or None for all."""
    return _out(_call("GET", "/api/ideas", params={"status": status} if status else None))


@mcp.tool()
def notify_user(text: str) -> str:
    """Send a message to the user through the Desk Telegram bot (if configured)."""
    return _out(_call("POST", "/api/notify", json={"text": text}))


@mcp.tool()
def refresh_data(job: str = "all") -> str:
    """Re-run data ingestion now. job: 'all' or one of hyperliquid_market, hyperliquid_account,
    coinbase, manual_positions, hyperliquid_candles, yahoo, fred, fred_calendar, deribit, defillama,
    cftc, earnings, short_interest, sec_13f, news, alerts."""
    return _out(_call("POST", f"/api/ingest/{job}"))


@mcp.tool()
def get_data_status() -> str:
    """When each data job last ran, whether it succeeded, and why it was skipped (e.g. missing key)."""
    return _out(_call("GET", "/api/ingest/status"))


def main(http: bool = False, host: str = "127.0.0.1", port: int = 8766) -> None:
    if http:
        try:
            mcp.run("streamable-http", host=host, port=port)
        except TypeError:  # mcp 1.x takes host/port via settings
            mcp.settings.host, mcp.settings.port = host, port  # type: ignore[attr-defined]
            mcp.run("streamable-http")
    else:
        mcp.run("stdio")
