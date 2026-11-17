from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from ..store import Store

RATE_UNITS = {"%", "bp"}
ABS_UNITS = {"corr", "z"}  # changes shown as absolute difference


def clean(x: Any) -> Any:
    """Make numpy/pandas values JSON-safe."""
    if isinstance(x, dict):
        return {k: clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [clean(v) for v in x]
    if isinstance(x, (np.floating, float)):
        f = float(x)
        return None if math.isnan(f) or math.isinf(f) else round(f, 6)
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, (pd.Timestamp,)):
        return x.isoformat()
    if isinstance(x, np.bool_):
        return bool(x)
    return x


def daily(s: pd.Series) -> pd.Series:
    if s.empty:
        return s
    return s.groupby(s.index.normalize()).last().sort_index()


def change(s: pd.Series, days: int, rate: bool) -> float | None:
    """Change vs the last observation at least `days` calendar days ago.
    Rates return basis points; everything else returns percent."""
    if len(s) < 2:
        return None
    cutoff = s.index[-1] - pd.Timedelta(days=days)
    past = s[s.index <= cutoff]
    if past.empty:
        return None
    a, b = float(past.iloc[-1]), float(s.iloc[-1])
    if rate == "abs":
        return b - a
    if rate:
        return (b - a) * 100.0
    return (b / a - 1.0) * 100.0 if a else None


def percentile(s: pd.Series, days: int = 365) -> float | None:
    if s.empty:
        return None
    window = s[s.index >= s.index[-1] - pd.Timedelta(days=days)]
    if len(window) < 20:
        return None
    return float((window <= window.iloc[-1]).mean() * 100.0)


def zscore(s: pd.Series, days: int = 365) -> float | None:
    window = s[s.index >= s.index[-1] - pd.Timedelta(days=days)] if not s.empty else s
    if len(window) < 20 or window.std() == 0:
        return None
    return float((window.iloc[-1] - window.mean()) / window.std())


def spark(s: pd.Series, n: int = 90) -> list[float]:
    return [round(float(v), 6) for v in s.iloc[-n:].values]


def indicator(store: Store, sid: str, name: str | None = None, unit: str | None = None,
              series: pd.Series | None = None) -> dict | None:
    s = daily(series if series is not None else store.series(sid, days=800))
    if s.empty:
        return None
    if name is None or unit is None:
        meta = store.query("SELECT name, unit FROM series_meta WHERE series_id = ?", [sid])
        if not meta.empty:
            name = name or meta["name"].iloc[0]
            unit = unit if unit is not None else meta["unit"].iloc[0]
    rate: bool | str = "abs" if unit in ABS_UNITS else unit in RATE_UNITS
    return {
        "id": sid, "name": name or sid, "unit": unit, "value": float(s.iloc[-1]),
        "as_of": s.index[-1].date().isoformat(),
        "chg_1d": change(s, 1, rate), "chg_1w": change(s, 7, rate), "chg_1m": change(s, 30, rate),
        "chg_unit": "" if rate == "abs" else "bp" if rate else "%", "pctile_1y": percentile(s), "z_1y": zscore(s),
        "spark": spark(s),
    }


def returns(s: pd.Series) -> pd.Series:
    return daily(s).pct_change().dropna()
