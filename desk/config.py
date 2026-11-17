from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(os.environ.get("DESK_HOME", Path(__file__).resolve().parent.parent))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:  # pragma: no cover
    pass


@lru_cache(maxsize=1)
def load() -> dict[str, Any]:
    path = Path(os.environ.get("DESK_CONFIG", ROOT / "config" / "desk.yaml"))
    with open(path) as f:
        return yaml.safe_load(f) or {}


def get(path: str, default: Any = None) -> Any:
    """Dotted lookup, e.g. get('portfolio.protected_spot')."""
    node: Any = load()
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node if node is not None else default


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip().strip('"')


def resolve(path: str) -> Path:
    p = Path(path)
    return p if p.is_absolute() else ROOT / p
