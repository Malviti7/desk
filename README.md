# Desk

A personal trading desk you own: the morning routine of a hedge fund PM, built on free data,
with an MCP server so your Hermes agents (or any MCP client) can use it as native tools.

```
             ┌──────────── data sources (scheduled) ────────────┐
             │ FRED · Yahoo · Hyperliquid · Deribit · DefiLlama │
             │ CFTC · Nasdaq · SEC EDGAR · RSS · Coinbase · CSV │
             └──────────────────────┬───────────────────────────┘
                                    ▼
   desk serve ──►  DuckDB  ──►  analytics (regime, crypto, positioning, risk, brief, alerts)
                                    │
             ┌──────────────────────┼─────────────────────────┐
             ▼                      ▼                         ▼
       Web dashboard           REST API /api/*          Telegram alerts
     (http://127.0.0.1:8765)        ▲
                                    │
                          desk mcp  (MCP server, 20 tools)
                                    ▲
                        Hermes agents · Claude · anything MCP
```

One process (`desk serve`) owns the database and runs the scheduler. The MCP server is a thin
client over the API, so agents never fight over the DuckDB file lock.

## Quick start

```bash
git clone <this repo> desk && cd desk
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[coinbase,dev]"
(cd web && npm install && npm run build)

desk serve --demo          # synthetic data, no keys: open http://127.0.0.1:8765
```

Then for real data:

```bash
cp .env.example .env       # add FRED_API_KEY, HYPERLIQUID_ADDRESS, etc.
cp config/positions.example.csv config/positions.csv   # optional: off-exchange holdings
desk serve                 # starts the scheduler; first full load takes a few minutes
```

Watch progress on the **Data** tab, or `curl -X POST localhost:8765/api/ingest/all`.
Jobs with missing keys are marked `skipped` with the reason, everything else still runs.

## What you get

| Tab | What's on it |
|---|---|
| **Morning** | Regime check, 1d P&L, gross/net, VaR, buffer before protected spot, alerts, biggest movers, overnight moves, 7-day calendar, crypto crowding, news on your book |
| **Macro** | Treasury curve vs 1 month ago, rates, net liquidity (Fed BS - TGA - RRP), credit spreads, vol (VIX term structure, MOVE), FX, futures, global indices, commodities, cross-asset correlations, economy, series explorer |
| **Crypto** | Hyperliquid perps (funding annualized, OI and 24h change, premium, crowding flags), funding/OI history charts, DVOL, stablecoin supply, TVL, trend vs 20/50/200d, crypto equities |
| **Equities** | Sector, index and factor performance, CFTC COT with 3y percentiles, short interest, 13F crowding |
| **Portfolio** | All positions across Hyperliquid, Coinbase and CSV with betas, days to exit, stop/target distance; Hyperliquid margin, liquidation distances, equity curve; exposures; thesis editor |
| **Risk** | Historical VaR/ES, hypothetical daily P&L of the current book, stress scenarios with Hyperliquid margin impact, custom stress, factor exposures, liquidity, correlation matrix, stops |
| **News & Calendar** | Filterable headlines tagged to your book and macro themes, 30-day calendar, 7 days of alerts |
| **Ideas** | Trade idea pipeline with price triggers that fire alerts |
| **Data** | Status of every ingest job, manual refresh |

### Protected spot

`portfolio.protected_spot` (default `[HYPE]`) marks spot you never want put at risk by perp
trading. Desk computes **buffer before protected spot** = account equity - protected spot value -
maintenance margin. Every stress scenario reports whether that buffer would go negative, and an
alert fires (severity `critical`) if it ever does live. There are no position or notional caps;
this is information, not a limit.

If you trade in a portfolio margin / unified account, keep `hyperliquid_unified: true` and check
that Desk's account value matches the Hyperliquid UI once. If it's off, flip the flag.

## Hermes integration

```bash
# 1. Give Hermes the tools (stdio; Hermes launches the process)
hermes mcp add desk --command "desk mcp"
hermes mcp test desk

# 2. Install the skills
cp -r hermes/skills/* ~/.hermes/skills/

# 3. Schedule the routine (check `hermes cron create --help` for delivery flags on your version)
hermes cron create "0 7 * * 1-5"      # prompt: "Run the desk-morning-brief skill"
hermes cron create "0 10-16/2 * * 1-5" # prompt: "Run the desk-regime-watch skill"
```

For an agent on another machine: run `desk mcp --http --host 0.0.0.0 --port 8766`, set
`DESK_API_TOKEN` in `.env`, and add it with `hermes mcp add desk --url http://<host>:8766/mcp`.
Put it behind Tailscale or similar rather than the open internet.

**Skills included** (`hermes/skills/`):

- `desk-morning-brief`: the full PM morning routine, ends with "today's top 3" and "add if / cut if".
- `desk-risk-check`: pre-trade check using what-if positions, plus playbooks for margin and protected-spot alerts.
- `desk-regime-watch`: intraday watch that only speaks when something changed.

**Wiring into your trading agent.** Your RiskEngine can call `POST /api/stress` with
`{"add": [{"symbol": "SOL", "notional": -50000}], "btc": -0.25}` before any order and reject trades
where `hyperliquid.protected_spot_at_risk` is true. The playbooks can pull `get_positioning`
(COT, short interest, 13F), `get_crypto_snapshot` (funding, OI) and `get_calendar` (catalysts).

### MCP tools

`get_morning_brief`, `get_regime`, `get_macro_snapshot`, `get_crypto_snapshot`,
`get_funding_history`, `get_positioning`, `get_portfolio`, `get_risk_report`, `run_stress_test`
(with what-if positions), `get_news`, `get_calendar`, `get_alerts`, `list_series`, `get_series`,
`set_thesis`, `add_idea`, `list_ideas`, `notify_user`, `refresh_data`, `get_data_status`.

Deliberately no order execution. Desk informs; your execution agent or you place trades.

## Data sources

| Data | Source | Cost | Key |
|---|---|---|---|
| Treasury yields, real yields, breakevens, fed funds, SOFR | FRED | Free | `FRED_API_KEY` |
| Fed balance sheet, RRP, TGA, reserves | FRED | Free | same |
| HY / IG credit spreads (ICE BofA OAS), NFCI, broad dollar | FRED | Free | same |
| Release calendar (CPI, NFP, PCE, GDP...) | FRED | Free | same |
| Futures, indices, VIX curve, MOVE, FX, commodities, ETFs, factors, sectors, equities | Yahoo Finance via yfinance | Free, delayed, unofficial | none |
| Perp prices, funding, OI, candles, your positions and margin | Hyperliquid info API | Free | `HYPERLIQUID_ADDRESS` (public) |
| BTC / ETH implied vol (DVOL) | Deribit | Free | none |
| Stablecoin supply, DeFi TVL | DefiLlama | Free | none |
| Futures positioning (COT) | CFTC | Free | none |
| Earnings calendar, short interest | Nasdaq API | Free, unofficial | none |
| 13F holdings | SEC EDGAR | Free | `SEC_USER_AGENT` |
| News | Fed, ECB, SEC, CoinDesk, Decrypt RSS + Google News | Free | none |
| Coinbase balances | Coinbase Advanced Trade | Free | view-only key |

**Upgrades worth paying for later:** Polygon or Tiingo for reliable real-time equities (replaces
yfinance), Coinglass or Velo for cross-venue funding/OI/liquidations, Financial Modeling Prep for
fundamentals, IBKR market data for real-time futures. Not replicable cheaply: Bloomberg, CDX,
real-time CME, prime broker crowding data. ETF flows (Farside) and token unlocks are not
included: Farside blocks scrapers and unlock APIs are paid. Add them as `manual_events` or a new
source module.

## Configuration

Everything lives in `config/desk.yaml`: which FRED series, Yahoo tickers, CFTC markets, 13F
filers, news feeds, crypto watchlist, alert thresholds, stress scenarios, and job schedules.
Restart `desk serve` after editing.

`config/positions.csv` columns: `account,symbol,asset_class,qty,entry_px,price_source`.
`asset_class` is one of `equity, etf, crypto_spot, crypto_perp, cash`; `price_source` is
`yahoo` or `hyperliquid`.

## Extending

- **New data source:** add a module in `desk/sources/` with `run(store) -> int`, register it in
  `desk/ingest.py`, give it a schedule in `desk.yaml`.
- **New regime signal:** add it in `desk/analytics/regime.py::regime`. It shows up on the
  dashboard, in the brief, in alerts (if red), and for agents automatically.
- **New MCP tool:** add an API route in `desk/api.py`, then a `@mcp.tool()` wrapper in
  `desk/mcp_server.py`.

## Commands

```
desk serve [--demo]     API + scheduler + dashboard
desk mcp [--http]       MCP server for agents
desk ingest [job|all]   run jobs once (stop `desk serve` first; it owns the DB)
desk status             job status
desk brief [--demo]     print the morning brief as markdown
desk demo               reseed demo data
pytest                  tests
cd web && npm run dev   dashboard dev server on :5173 with hot reload
```

## Notes

- All analytics are deterministic Python on stored data. Agents read numbers; they don't make them up.
- Betas use 180 days of daily returns; VaR uses `var_lookback_days` of history applied to today's
  book (crypto trades weekends, so equity returns are 0 on those days).
- The Fed path signal is a proxy (2Y vs funds midpoint), not FedWatch. CME's data is paid.
- Not investment advice. Check numbers against your venues before acting on them.
