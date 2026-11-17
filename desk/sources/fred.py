"""FRED (free, API key). Rates, liquidity, credit spreads, FX, economy, release calendar."""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from .. import config
from ..store import Store
from . import get_json

BASE = "https://api.stlouisfed.org/fred"


def _key() -> str:
    k = config.env("FRED_API_KEY")
    if not k:
        raise RuntimeError("FRED_API_KEY not set (free at fred.stlouisfed.org)")
    return k


def fetch(series_id: str, start: str) -> pd.Series:
    data = get_json(f"{BASE}/series/observations", {
        "series_id": series_id, "api_key": _key(), "file_type": "json",
        "observation_start": start,
    })
    obs = [(o["date"], o["value"]) for o in data.get("observations", []) if o["value"] not in (".", "")]
    if not obs:
        return pd.Series(dtype=float)
    idx, vals = zip(*obs)
    return pd.Series([float(v) for v in vals], index=pd.to_datetime(list(idx)))


def run(store: Store) -> int:
    start = (date.today() - timedelta(days=365 * 3)).isoformat()
    n = 0
    for sid, (name, cat, unit) in config.get("fred_series", {}).items():
        n += store.upsert_series(f"fred:{sid}", fetch(sid, start), "fred", name, cat, unit)
    return n


def run_calendar(store: Store) -> int:
    """Upcoming data releases from FRED plus FOMC dates and manual events."""
    rows: list[dict] = []
    today = date.today()
    wanted = [w.lower() for w in config.get("calendar_releases", [])]
    try:
        data = get_json(f"{BASE}/releases/dates", {
            "api_key": _key(), "file_type": "json",
            "realtime_start": today.isoformat(),
            "realtime_end": (today + timedelta(days=45)).isoformat(),
            "include_release_dates_with_no_data": "true",
            "limit": 1000, "sort_order": "asc",
        })
        for r in data.get("release_dates", []):
            name = r.get("release_name", "")
            if any(w in name.lower() for w in wanted):
                rows.append({"date": r["date"], "kind": "macro", "name": name, "detail": "", "source": "fred"})
    except RuntimeError:
        pass  # no key: still write FOMC + manual events
    for d in config.get("fomc_dates", []):
        if date.fromisoformat(d) >= today:
            rows.append({"date": d, "kind": "macro", "name": "FOMC decision", "detail": "2:00pm ET", "source": "config"})
    for e in config.get("manual_events", []) or []:
        rows.append({"date": e["date"], "kind": e.get("kind", "event"), "name": e["name"],
                     "detail": e.get("detail", ""), "source": "config"})
    df = pd.DataFrame(rows).drop_duplicates(subset=["date", "name"]) if rows else pd.DataFrame()
    store.execute("DELETE FROM calendar WHERE source IN ('fred', 'config')")
    if df.empty:
        return 0
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return store.insert_df("calendar", df)
