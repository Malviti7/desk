"""News from free RSS: central banks, SEC, crypto outlets, and Google News queries
(including one per held symbol). Headlines are tagged against your book."""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus

import feedparser
import pandas as pd

from .. import config
from ..store import Store
from . import UA

ALIASES = {
    "BTC": ["bitcoin", "btc"], "ETH": ["ethereum", "ether", "eth"], "SOL": ["solana"],
    "HYPE": ["hyperliquid", "hype"], "SPY": ["s&p 500"], "TLT": ["treasur"],
}
MACRO_TAGS = {
    "fed": ["federal reserve", "fomc", "powell", "rate cut", "rate hike"],
    "rates": ["treasury yield", "bond", "10-year", "2-year"],
    "inflation": ["inflation", "cpi", "pce"],
    "jobs": ["payroll", "jobless", "unemployment"],
    "geopolitics": ["tariff", "sanction", "china", "war", "opec"],
    "japan": ["bank of japan", "boj", "yen"],
    "crypto-reg": ["sec ", "cftc", "stablecoin bill", "regulat"],
}


def _held(store: Store) -> list[str]:
    return [s for s in store.query("SELECT DISTINCT symbol FROM positions WHERE asset_class <> 'cash'")
            .get("symbol", [])]


def _feeds(store: Store) -> dict[str, str]:
    cfg = config.get("news", {})
    feeds = dict(cfg.get("feeds") or {})
    g = "https://news.google.com/rss/search?q={}&hl=en-US&gl=US&ceid=US:en"
    for q in cfg.get("google_news_queries") or []:
        feeds[f"Google: {q}"] = g.format(quote_plus(q + " when:2d"))
    if cfg.get("include_position_queries", True):
        for s in _held(store):
            term = ALIASES.get(s, [s])[0]
            feeds[f"Google: {s}"] = g.format(quote_plus(f'"{term}" when:2d'))
    return feeds


def tag(text: str, symbols: list[str]) -> list[str]:
    t = f" {text.lower()} "
    tags = []
    for s in symbols:
        words = ALIASES.get(s, []) + [s.lower()]
        if any(re.search(rf"\b{re.escape(w)}", t) for w in words):
            tags.append(f"${s}")
    for k, words in MACRO_TAGS.items():
        if any(w in t for w in words):
            tags.append(k)
    return tags


def run(store: Store) -> int:
    symbols = sorted(set(_held(store)) | set(config.get("crypto.watch", [])))
    cutoff = datetime.now(timezone.utc) - timedelta(hours=int(config.get("news.max_age_hours", 72)))
    rows = []
    for source, url in _feeds(store).items():
        try:
            feed = feedparser.parse(url, agent=UA)
        except Exception:  # noqa: BLE001
            continue
        for e in feed.entries[:40]:
            tm = e.get("published_parsed") or e.get("updated_parsed")
            ts = datetime(*tm[:6], tzinfo=timezone.utc) if tm else datetime.now(timezone.utc)
            if ts < cutoff:
                continue
            title = re.sub(r"\s+", " ", e.get("title", "")).strip()
            summary = re.sub(r"<[^>]+>", "", e.get("summary", ""))[:400]
            link = e.get("link", "")
            rows.append({
                "id": hashlib.sha1((title.lower()[:120]).encode()).hexdigest()[:16],
                "ts": ts.replace(tzinfo=None), "source": source, "title": title, "url": link,
                "summary": summary, "tags": ",".join(tag(f"{title} {summary}", symbols)),
            })
    if not rows:
        return 0
    df = pd.DataFrame(rows).drop_duplicates("id")
    store.execute("DELETE FROM news WHERE ts < now()::TIMESTAMP - INTERVAL 14 DAY")
    return store.insert_df("news", df, replace_keys=["id"])
