"""desk CLI.

  desk serve [--demo]        API + scheduler + dashboard on http://127.0.0.1:8765
  desk mcp [--http]          MCP server for agents (talks to the API)
  desk ingest [JOB|all]      run data jobs once (stop `desk serve` first: it owns the DB)
  desk status                last run of each job
  desk brief                 print the morning brief as markdown
  desk demo                  seed data/demo.duckdb with synthetic data
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from . import config


def _use_demo_db() -> None:
    os.environ["DESK_DEMO"] = "1"
    os.environ["DESK_NO_SCHEDULER"] = "1"
    import desk.store as st

    st._store = st.Store(str(config.resolve("data/demo.duckdb")))


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="desk", description="Your personal trading desk")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve")
    s.add_argument("--demo", action="store_true", help="serve synthetic demo data, no scheduler")
    s.add_argument("--host")
    s.add_argument("--port", type=int)
    m = sub.add_parser("mcp")
    m.add_argument("--http", action="store_true")
    m.add_argument("--host", default="127.0.0.1")
    m.add_argument("--port", type=int, default=8766)
    i = sub.add_parser("ingest")
    i.add_argument("job", nargs="?", default="all")
    sub.add_parser("status")
    b = sub.add_parser("brief")
    b.add_argument("--demo", action="store_true")
    sub.add_parser("demo")
    a = p.parse_args(argv)

    if a.cmd == "serve":
        import uvicorn

        if a.demo:
            _use_demo_db()
            if not config.resolve("data/demo.duckdb").exists() or _empty_demo():
                _seed_demo()
        uvicorn.run("desk.api:app", host=a.host or config.get("server.host", "127.0.0.1"),
                    port=a.port or int(config.get("server.port", 8765)), log_level="info")
    elif a.cmd == "mcp":
        from .mcp_server import main as mcp_main

        mcp_main(http=a.http, host=a.host, port=a.port)
    elif a.cmd == "ingest":
        from . import ingest
        from .store import get_store

        res = ingest.run_all(get_store()) if a.job == "all" else [ingest.run_job(get_store(), a.job)]
        for r in res:
            print(json.dumps(r))
    elif a.cmd == "status":
        from . import ingest
        from .store import get_store

        for r in ingest.status(get_store()):
            print(f"{r['job']:<22} {r['last_status']:<8} last={r['last_run']}  {(r['last_error'] or '')[:80]}")
    elif a.cmd == "brief":
        if a.demo:
            _use_demo_db()
        from .analytics import brief
        from .store import get_store

        print(brief.to_markdown(brief.build(get_store())))
    elif a.cmd == "demo":
        _use_demo_db()
        _seed_demo()
        print("Seeded data/demo.duckdb. Run: desk serve --demo")


def _empty_demo() -> bool:
    from .store import get_store

    return get_store().query("SELECT count(*) AS n FROM series")["n"].iloc[0] == 0


def _seed_demo() -> None:
    from . import demo
    from .store import get_store

    st = get_store()
    for t in ["series", "series_meta", "perp_snapshots", "positions", "account_state", "news", "calendar", "cot",
              "short_interest", "holdings_13f", "theses", "ideas", "alerts", "ingest_log"]:
        st.execute(f"DELETE FROM {t}")
    demo.seed(st)
    from . import alerts

    alerts.run(st)


if __name__ == "__main__":
    main(sys.argv[1:])
