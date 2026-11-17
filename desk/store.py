"""DuckDB storage. One process (`desk serve`) owns the database file.

Everything else (MCP server, scripts, agents) goes through the REST API,
which avoids DuckDB's single-writer file lock.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from typing import Any, Iterable

import duckdb
import pandas as pd

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS series (
  series_id VARCHAR, ts TIMESTAMP, value DOUBLE, source VARCHAR,
  PRIMARY KEY (series_id, ts)
);
CREATE TABLE IF NOT EXISTS series_meta (
  series_id VARCHAR PRIMARY KEY, name VARCHAR, category VARCHAR,
  unit VARCHAR, source VARCHAR
);
CREATE TABLE IF NOT EXISTS perp_snapshots (
  ts TIMESTAMP, venue VARCHAR, coin VARCHAR, mark DOUBLE, oracle DOUBLE,
  funding DOUBLE, open_interest DOUBLE, oi_usd DOUBLE, volume_24h DOUBLE,
  premium DOUBLE, prev_day_px DOUBLE
);
CREATE TABLE IF NOT EXISTS positions (
  ts TIMESTAMP, account VARCHAR, venue VARCHAR, symbol VARCHAR,
  asset_class VARCHAR, qty DOUBLE, entry_px DOUBLE, price DOUBLE,
  notional DOUBLE, unrealized_pnl DOUBLE, leverage DOUBLE,
  liquidation_px DOUBLE, margin_used DOUBLE, price_source VARCHAR
);
CREATE TABLE IF NOT EXISTS account_state (
  ts TIMESTAMP, account VARCHAR, venue VARCHAR, account_value DOUBLE,
  maint_margin DOUBLE, margin_used DOUBLE, withdrawable DOUBLE, raw JSON
);
CREATE TABLE IF NOT EXISTS news (
  id VARCHAR PRIMARY KEY, ts TIMESTAMP, source VARCHAR, title VARCHAR,
  url VARCHAR, summary VARCHAR, tags VARCHAR
);
CREATE TABLE IF NOT EXISTS calendar (
  date DATE, kind VARCHAR, name VARCHAR, detail VARCHAR, source VARCHAR
);
CREATE TABLE IF NOT EXISTS cot (
  report_date DATE, code VARCHAR, market VARCHAR, open_interest DOUBLE,
  noncomm_long DOUBLE, noncomm_short DOUBLE, comm_long DOUBLE, comm_short DOUBLE,
  PRIMARY KEY (report_date, code)
);
CREATE TABLE IF NOT EXISTS short_interest (
  symbol VARCHAR, settlement_date DATE, short_interest DOUBLE,
  avg_daily_volume DOUBLE, days_to_cover DOUBLE,
  PRIMARY KEY (symbol, settlement_date)
);
CREATE TABLE IF NOT EXISTS holdings_13f (
  cik VARCHAR, fund VARCHAR, period DATE, issuer VARCHAR, cusip VARCHAR,
  value_usd DOUBLE, shares DOUBLE
);
CREATE TABLE IF NOT EXISTS theses (
  symbol VARCHAR PRIMARY KEY, direction VARCHAR, thesis VARCHAR,
  stop DOUBLE, target DOUBLE, catalyst VARCHAR, catalyst_date DATE,
  updated_at TIMESTAMP, updated_by VARCHAR
);
CREATE TABLE IF NOT EXISTS ideas (
  id INTEGER PRIMARY KEY, symbol VARCHAR, direction VARCHAR,
  trigger_px DOUBLE, trigger_dir VARCHAR, note VARCHAR,
  status VARCHAR, created_at TIMESTAMP, created_by VARCHAR
);
CREATE SEQUENCE IF NOT EXISTS ideas_seq START 1;
CREATE TABLE IF NOT EXISTS alerts (
  key VARCHAR PRIMARY KEY, ts TIMESTAMP, severity VARCHAR,
  category VARCHAR, message VARCHAR, sent BOOLEAN
);
CREATE TABLE IF NOT EXISTS ingest_log (
  job VARCHAR, ts TIMESTAMP, status VARCHAR, rows INTEGER, error VARCHAR
);
"""


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Store:
    def __init__(self, path: str | None = None):
        db_path = path or str(config.resolve(config.get("server.db_path", "data/desk.duckdb")))
        if db_path != ":memory:":
            config.resolve(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.con = duckdb.connect(db_path)
        self.lock = threading.RLock()
        with self.lock:
            self.con.execute(SCHEMA)

    # ------------------------------------------------------------ basics
    def query(self, sql: str, params: Iterable[Any] | None = None) -> pd.DataFrame:
        with self.lock:
            return self.con.execute(sql, list(params or [])).df()

    def execute(self, sql: str, params: Iterable[Any] | None = None) -> None:
        with self.lock:
            self.con.execute(sql, list(params or []))

    def records(self, sql: str, params: Iterable[Any] | None = None) -> list[dict]:
        df = self.query(sql, params)
        return json.loads(df.to_json(orient="records", date_format="iso"))

    def insert_df(self, table: str, df: pd.DataFrame, replace_keys: list[str] | None = None) -> int:
        """Insert a dataframe. If replace_keys given, delete matching rows first (upsert)."""
        if df is None or df.empty:
            return 0
        with self.lock:
            self.con.register("_incoming", df)
            try:
                cols = ", ".join(df.columns)
                if replace_keys:
                    cond = " AND ".join(f"t.{k} = i.{k}" for k in replace_keys)
                    self.con.execute(
                        f"DELETE FROM {table} t WHERE EXISTS (SELECT 1 FROM _incoming i WHERE {cond})"
                    )
                self.con.execute(f"INSERT INTO {table} ({cols}) SELECT {cols} FROM _incoming")
            finally:
                self.con.unregister("_incoming")
        return len(df)

    # ------------------------------------------------------------ series
    def upsert_series(self, series_id: str, points: pd.Series, source: str,
                      name: str | None = None, category: str | None = None,
                      unit: str | None = None) -> int:
        points = points.dropna()
        if points.empty:
            return 0
        df = pd.DataFrame({
            "series_id": series_id,
            "ts": pd.to_datetime(points.index).tz_localize(None) if getattr(points.index, "tz", None) else pd.to_datetime(points.index),
            "value": points.astype(float).values,
            "source": source,
        })
        n = self.insert_df("series", df, replace_keys=["series_id", "ts"])
        if name:
            self.execute(
                "INSERT OR REPLACE INTO series_meta VALUES (?, ?, ?, ?, ?)",
                [series_id, name, category, unit, source],
            )
        return n

    def series(self, series_id: str, days: int | None = None) -> pd.Series:
        sql = "SELECT ts, value FROM series WHERE series_id = ?"
        params: list[Any] = [series_id]
        if days:
            sql += f" AND ts >= now()::TIMESTAMP - INTERVAL {int(days)} DAY"
        df = self.query(sql + " ORDER BY ts", params)
        if df.empty:
            return pd.Series(dtype=float, name=series_id)
        return pd.Series(df["value"].values, index=pd.to_datetime(df["ts"]), name=series_id)

    def series_frame(self, ids: list[str], days: int | None = None) -> pd.DataFrame:
        cols = {i: self.series(i, days) for i in ids}
        cols = {k: v for k, v in cols.items() if not v.empty}
        if not cols:
            return pd.DataFrame()
        # Normalize to daily so sources with different timestamps line up
        frame = pd.DataFrame({k: v.groupby(v.index.normalize()).last() for k, v in cols.items()})
        return frame.sort_index()

    # ------------------------------------------------------------ logging
    def log(self, job: str, status: str, rows: int = 0, error: str | None = None) -> None:
        self.execute("INSERT INTO ingest_log VALUES (?, ?, ?, ?, ?)", [job, utcnow(), status, rows, error])


_store: Store | None = None


def get_store() -> Store:
    global _store
    if _store is None:
        _store = Store()
    return _store
