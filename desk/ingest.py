"""Job registry and a lightweight scheduler that runs inside `desk serve`."""
from __future__ import annotations

import asyncio
import logging
import time
import traceback
from typing import Callable

from . import config
from .store import Store

log = logging.getLogger("desk.ingest")


def _jobs() -> dict[str, Callable[[Store], int]]:
    from .sources import accounts, coinalyze, crypto_extra, fred, hyperliquid, news, positioning, yahoo
    from . import alerts

    # Order matters on a full refresh: positions first so other jobs know what you hold.
    return {
        "hyperliquid_market": hyperliquid.run_market,
        "hyperliquid_account": hyperliquid.run_account,
        "coinbase": accounts.run_coinbase,
        "manual_positions": accounts.run_manual,
        "hyperliquid_candles": hyperliquid.run_candles,
        "yahoo": yahoo.run,
        "fred": fred.run,
        "fred_calendar": fred.run_calendar,
        "coinalyze": coinalyze.run,
        "coinalyze_history": coinalyze.run_history,
        "deribit": crypto_extra.run_deribit,
        "defillama": crypto_extra.run_defillama,
        "cftc": positioning.run_cftc,
        "earnings": positioning.run_earnings,
        "short_interest": positioning.run_short_interest,
        "sec_13f": positioning.run_13f,
        "news": news.run,
        "alerts": alerts.run,
    }


JOBS = _jobs


def run_job(store: Store, name: str) -> dict:
    fn = _jobs().get(name)
    if fn is None:
        return {"job": name, "status": "unknown"}
    t0 = time.time()
    try:
        rows = fn(store)
        store.log(name, "ok", rows)
        return {"job": name, "status": "ok", "rows": rows, "secs": round(time.time() - t0, 1)}
    except RuntimeError as e:  # configuration problems (missing keys) are expected, not crashes
        store.log(name, "skipped", 0, str(e))
        return {"job": name, "status": "skipped", "reason": str(e)}
    except Exception as e:  # noqa: BLE001
        log.warning("job %s failed: %s", name, e)
        store.log(name, "error", 0, f"{e}\n{traceback.format_exc()[-800:]}")
        return {"job": name, "status": "error", "error": str(e)}


def run_all(store: Store) -> list[dict]:
    # positions before market-dependent jobs, then re-run manual so prices resolve
    results = [run_job(store, j) for j in _jobs()]
    results.append(run_job(store, "manual_positions"))
    return results


def status(store: Store) -> list[dict]:
    return store.records("""
        SELECT job, max(ts) AS last_run,
               arg_max(status, ts) AS last_status,
               arg_max(rows, ts) AS last_rows,
               arg_max(error, ts) AS last_error,
               max(CASE WHEN status = 'ok' THEN ts END) AS last_ok
        FROM ingest_log GROUP BY job ORDER BY job""")


async def scheduler(store: Store) -> None:
    """Runs each job on its configured interval. Jobs run in a thread so the API stays responsive."""
    schedule = {k: int(v) for k, v in (config.get("schedule") or {}).items() if int(v or 0) > 0}
    last: dict[str, float] = {}
    await asyncio.sleep(2)
    while True:
        now = time.time()
        for job, minutes in schedule.items():
            if now - last.get(job, 0) >= minutes * 60:
                last[job] = now
                await asyncio.to_thread(run_job, store, job)
        await asyncio.sleep(20)
