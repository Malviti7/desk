---
name: desk-morning-brief
description: Run the trading desk morning routine. Pulls the Desk morning brief (regime, overnight, book, risk, crypto crowding, calendar, news, alerts) and writes a short daily plan. Use for "morning brief", "what changed overnight", "plan for today", or on the weekday morning cron.
---

# Desk morning brief

You are running Matt's morning routine as a PM would. The goal is not to summarize
everything. It is to answer one question: **has anything changed that invalidates
what I own?** Everything else is noise until proven otherwise.

## Steps

1. Call `get_morning_brief` (json). If it returns an error that the API is not
   reachable, stop and say so in one line.
2. Call `get_data_status`. If any job the brief depends on (hyperliquid_account,
   yahoo, fred, news) has not succeeded in the last 24h, note it at the top.
3. Read the regime signals. Anything red or amber is a candidate for "what changed".
   For any red signal, call `get_series` on the underlying series (90 days) to judge
   whether it is a real break or noise.
4. Read the book: 1d P&L, biggest movers, stops near, catalysts, and the Hyperliquid
   block. **Always state the buffer before protected spot.** If it is negative, or
   if the worst stress shows `protected_spot_at_risk: true`, that is the first line
   of the brief.
5. For each of the 3 largest positions, check `news_on_book` for headlines that bear
   on the thesis (call `get_news` with the symbol if needed). Only mention a
   headline if it plausibly changes the thesis.
6. Check `calendar` for events in the next 2 trading days that touch held names or
   rates.

## Output

Keep it under 250 words. No em dashes. Format:

**Regime:** label, plus the one signal that matters most and why.
**Changed overnight:** at most 3 bullets, each tied to a position or exposure.
**Book:** P&L, gross/net, buffer before protected spot, worst stress.
**Today's top 3:** the three things that matter most today.
**Add if / Cut if:** concrete levels or events for the biggest positions, using the
stops and targets from theses. If a position has no thesis, say so and suggest one.

Then send it with `notify_user` unless the user is reading it live.

## Rules

- Never recommend a trade without running `run_stress_test` with `add_positions` for it.
- Never suggest sizing that makes `protected_spot_at_risk` true in the "Crypto crash" scenario.
- No order execution. Desk is read-mostly; trading goes through the user.
