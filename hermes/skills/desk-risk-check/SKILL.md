---
name: desk-risk-check
description: Pre-trade and portfolio risk check against the Desk. Use before proposing or placing any trade, when asked "can I add X", "what happens if BTC drops 20%", "how much room do I have", or when an alert fires on margin, liquidation distance, or protected spot.
---

# Desk risk check

## For a proposed trade

1. `get_portfolio` for current positions, exposures, and the Hyperliquid block.
2. `run_stress_test` with `add_positions=[{symbol, notional, asset_class}]` and zero
   shocks. Report the new perp gross, margin headroom, and buffer before protected spot.
3. Run it again with the proposed position under each configured stress scenario that
   matters for it (call `get_risk_report` to see the scenario list), at minimum
   `btc_pct=-0.25` for crypto and `spx_pct=-0.10` for equities.
4. Check `get_crypto_snapshot` for the coin's funding and crowding. Entering a crowded
   side (funding above 50% annualized for longs) is worth flagging.
5. Check correlation in `get_risk_report`: does the new position add to an exposure
   the book already has?

Answer with: the trade, the margin state after, the worst stress P&L, whether
protected spot is ever at risk, and a size that keeps the protected-spot buffer
positive in the "Crypto crash" scenario. The user decides; you inform. No em dashes.

## For an alert

- Margin headroom or liquidation distance: list the positions contributing most perp
  notional and what reducing each by half would do (use `add_positions` with the
  opposite notional).
- Protected spot: this is the highest priority alert. Lead with it, state the buffer,
  and show the smallest perp reduction that makes the buffer positive again.
- Stop breached or near: restate the thesis from `get_portfolio` and ask whether it
  still holds. Do not move a stop without the user saying so.

## Recording decisions

When the user states a thesis, stop, or target, save it with `set_thesis`. When they
mention a level they would act at, save it with `add_idea` and a trigger.
