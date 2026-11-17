"""REST API + scheduler + static dashboard. Run with `desk serve`."""
from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import alerts as alerts_mod
from . import config, ingest
from .analytics import brief, crypto, positioning, regime, risk
from .analytics.common import clean, daily, indicator
from .store import Store, get_store, utcnow

WEB_DIST = config.ROOT / "web" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = None
    if os.environ.get("DESK_NO_SCHEDULER") != "1":
        task = asyncio.create_task(ingest.scheduler(store()))
    yield
    if task:
        task.cancel()


app = FastAPI(title="Desk", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])


def store() -> Store:
    return get_store()


def auth(request: Request) -> None:
    token = config.env("DESK_API_TOKEN")
    if token and request.headers.get("authorization", "") != f"Bearer {token}":
        raise HTTPException(401, "Bad or missing bearer token")


api = Depends(auth)


# ------------------------------------------------------------------ read endpoints
@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "time": utcnow().isoformat(), "demo": os.environ.get("DESK_DEMO") == "1"}


@app.get("/api/brief", dependencies=[api])
def get_brief() -> dict:
    return brief.build(store())


@app.get("/api/brief.md", dependencies=[api], response_class=PlainTextResponse)
def get_brief_md() -> str:
    return brief.to_markdown(brief.build(store()))


@app.get("/api/regime", dependencies=[api])
def get_regime() -> dict:
    return regime.regime(store())


@app.get("/api/macro", dependencies=[api])
def get_macro() -> dict:
    return regime.macro_snapshot(store())


@app.get("/api/crypto", dependencies=[api])
def get_crypto() -> dict:
    return crypto.snapshot(store())


@app.get("/api/crypto/funding/{coin}", dependencies=[api])
def get_funding(coin: str, days: int = 14) -> list[dict]:
    return crypto.funding_history(store(), coin.upper(), days)


@app.get("/api/equities", dependencies=[api])
def get_equities() -> dict:
    return positioning.snapshot(store())


@app.get("/api/portfolio", dependencies=[api])
def get_portfolio() -> dict:
    return risk.portfolio(store())


@app.get("/api/risk", dependencies=[api])
def get_risk() -> dict:
    return risk.report(store())


class Scenario(BaseModel):
    name: str = "custom"
    spx: float = 0.0
    btc: float = 0.0
    overrides: dict[str, float] = {}
    add: list[dict] = []  # what-if positions: [{"symbol": "SOL", "notional": -50000, "asset_class": "crypto_perp"}]


@app.post("/api/stress", dependencies=[api])
def post_stress(s: Scenario) -> dict:
    return risk.run_stress(store(), s.model_dump())


@app.get("/api/news", dependencies=[api])
def get_news(limit: int = 60, book_only: bool = False, q: str | None = None) -> list[dict]:
    return brief.news(store(), limit, book_only, q)


@app.get("/api/calendar", dependencies=[api])
def get_calendar(days: int = 14) -> list[dict]:
    return brief.calendar(store(), days)


@app.get("/api/alerts", dependencies=[api])
def get_alerts(hours: int = 72) -> list[dict]:
    return brief.alerts(store(), hours)


@app.get("/api/series", dependencies=[api])
def list_series(q: str | None = None) -> list[dict]:
    sql = """SELECT m.series_id, m.name, m.category, m.unit, m.source, max(s.ts)::VARCHAR AS last
             FROM series_meta m LEFT JOIN series s USING (series_id)"""
    params: list[Any] = []
    if q:
        sql += " WHERE lower(m.series_id) LIKE ? OR lower(m.name) LIKE ?"
        params = [f"%{q.lower()}%"] * 2
    return store().records(sql + " GROUP BY ALL ORDER BY m.category, m.series_id", params)


@app.get("/api/series/{series_id:path}", dependencies=[api])
def get_series(series_id: str, days: int = 365) -> dict:
    s = daily(store().series(series_id, days))
    if s.empty:
        raise HTTPException(404, f"No data for {series_id}")
    ind = indicator(store(), series_id, series=s) or {}
    ind.pop("spark", None)
    return clean({**ind, "points": [{"date": d.date().isoformat(), "value": float(v)} for d, v in s.items()]})


# ------------------------------------------------------------------ notes agents can write
class Thesis(BaseModel):
    symbol: str
    direction: str = "long"
    thesis: str = ""
    stop: float | None = None
    target: float | None = None
    catalyst: str | None = None
    catalyst_date: date | None = None
    updated_by: str = "user"


@app.get("/api/theses", dependencies=[api])
def get_theses() -> list[dict]:
    return store().records("SELECT * FROM theses ORDER BY symbol")


@app.put("/api/theses", dependencies=[api])
def put_thesis(t: Thesis) -> dict:
    store().execute("INSERT OR REPLACE INTO theses VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", [
        t.symbol.upper(), t.direction, t.thesis, t.stop, t.target, t.catalyst, t.catalyst_date, utcnow(), t.updated_by])
    return {"ok": True}


@app.delete("/api/theses/{symbol}", dependencies=[api])
def delete_thesis(symbol: str) -> dict:
    store().execute("DELETE FROM theses WHERE symbol = ?", [symbol.upper()])
    return {"ok": True}


class Idea(BaseModel):
    symbol: str
    direction: str = "long"
    trigger_px: float | None = None
    trigger_dir: str = "below"  # 'above' or 'below'
    note: str = ""
    created_by: str = "user"


@app.get("/api/ideas", dependencies=[api])
def get_ideas(status: str | None = None) -> list[dict]:
    sql, params = "SELECT * FROM ideas", []
    if status:
        sql, params = sql + " WHERE status = ?", [status]
    return store().records(sql + " ORDER BY created_at DESC", params)


@app.post("/api/ideas", dependencies=[api])
def post_idea(i: Idea) -> dict:
    store().execute("INSERT INTO ideas VALUES (nextval('ideas_seq'), ?, ?, ?, ?, ?, 'open', ?, ?)", [
        i.symbol.upper(), i.direction, i.trigger_px, i.trigger_dir, i.note, utcnow(), i.created_by])
    return {"ok": True}


@app.delete("/api/ideas/{idea_id}", dependencies=[api])
def close_idea(idea_id: int) -> dict:
    store().execute("UPDATE ideas SET status = 'closed' WHERE id = ?", [idea_id])
    return {"ok": True}


# ------------------------------------------------------------------ ops
@app.get("/api/ingest/status", dependencies=[api])
def ingest_status() -> list[dict]:
    return ingest.status(store())


@app.post("/api/ingest/{job}", dependencies=[api])
async def ingest_run(job: str) -> Any:
    if job == "all":
        return await asyncio.to_thread(ingest.run_all, store())
    if job not in ingest.JOBS():
        raise HTTPException(404, f"Unknown job. Options: all, {', '.join(ingest.JOBS())}")
    return await asyncio.to_thread(ingest.run_job, store(), job)


class Notify(BaseModel):
    text: str


@app.post("/api/notify", dependencies=[api])
def notify(n: Notify) -> dict:
    """Lets agents push a message through the Desk's Telegram bot."""
    return {"sent": alerts_mod.send(n.text)}


# ------------------------------------------------------------------ dashboard
if WEB_DIST.exists():
    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        f = WEB_DIST / path
        return FileResponse(f if path and f.is_file() else WEB_DIST / "index.html")
