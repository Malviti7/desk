"""Data source connectors. Each exposes `run(store) -> int` (rows written)."""
from __future__ import annotations

import httpx

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"


def client(timeout: float = 20.0, headers: dict | None = None) -> httpx.Client:
    h = {"User-Agent": UA, "Accept": "application/json, text/plain, */*"}
    h.update(headers or {})
    return httpx.Client(timeout=timeout, headers=h, follow_redirects=True)


def get_json(url: str, params: dict | None = None, headers: dict | None = None, retries: int = 2):
    last: Exception | None = None
    for _ in range(retries + 1):
        try:
            with client(headers=headers) as c:
                r = c.get(url, params=params)
                r.raise_for_status()
                return r.json()
        except Exception as e:  # noqa: BLE001
            last = e
    raise last  # type: ignore[misc]


def post_json(url: str, payload: dict, retries: int = 2):
    last: Exception | None = None
    for _ in range(retries + 1):
        try:
            with client() as c:
                r = c.post(url, json=payload)
                r.raise_for_status()
                return r.json()
        except Exception as e:  # noqa: BLE001
            last = e
    raise last  # type: ignore[misc]
