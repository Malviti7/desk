---
name: desk-regime-watch
description: Intraday watch on the Desk. Checks regime signals and new alerts, and messages the user only when something changed. Use on an every-2-hours cron during market hours, or when asked "anything I should know right now".
---

> Tool names below come from the Desk Hermes plugin. If you connected Desk over MCP instead, use the matching MCP tool (e.g. `desk_portfolio` is `get_portfolio`, `desk_stress_test` is `run_stress_test`).

# Desk regime watch

1. Call `desk_regime` and `desk_alerts` with `hours=3`.
2. Compare with what you reported last time (your memory of the previous run). Only
   continue if:
   - the regime label changed, or
   - a signal turned red, or
   - there is a new alert with severity high or critical.
3. If nothing changed, end silently. Do not send "all clear" messages.
4. If something changed, call `desk_portfolio` and say in 2 to 4 lines what changed and
   which positions it touches. If the alert is margin or protected spot, follow the
   desk-risk-check skill instead.
5. Send with `desk_notify`. No em dashes.
