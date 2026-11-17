"""Positioning data (all free): CFTC COT, short interest and earnings (Nasdaq, unofficial),
13F holdings (SEC EDGAR)."""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import date, timedelta

import pandas as pd

from .. import config
from ..store import Store
from . import client, get_json

NASDAQ_HEADERS = {"Origin": "https://www.nasdaq.com", "Referer": "https://www.nasdaq.com/"}


# ------------------------------------------------------------------ CFTC
def run_cftc(store: Store) -> int:
    markets = config.get("cftc_markets", {})
    if not markets:
        return 0
    codes = ",".join(f"'{c}'" for c in markets)
    since = (date.today() - timedelta(days=365 * 3)).isoformat()
    rows = get_json("https://publicreporting.cftc.gov/resource/6dca-aqww.json", {
        "$where": f"cftc_contract_market_code in ({codes}) AND report_date_as_yyyy_mm_dd >= '{since}'",
        "$limit": 50000,
        "$order": "report_date_as_yyyy_mm_dd",
    })
    out = []
    for r in rows:
        code = r.get("cftc_contract_market_code")
        out.append({
            "report_date": r["report_date_as_yyyy_mm_dd"][:10], "code": code,
            "market": markets.get(code, r.get("market_and_exchange_names")),
            "open_interest": float(r.get("open_interest_all", 0) or 0),
            "noncomm_long": float(r.get("noncomm_positions_long_all", 0) or 0),
            "noncomm_short": float(r.get("noncomm_positions_short_all", 0) or 0),
            "comm_long": float(r.get("comm_positions_long_all", 0) or 0),
            "comm_short": float(r.get("comm_positions_short_all", 0) or 0),
        })
    df = pd.DataFrame(out)
    if df.empty:
        return 0
    df["report_date"] = pd.to_datetime(df["report_date"]).dt.date
    return store.insert_df("cot", df, replace_keys=["report_date", "code"])


# ------------------------------------------------------------------ Earnings
def run_earnings(store: Store) -> int:
    held = set(store.query("SELECT DISTINCT symbol FROM positions WHERE asset_class IN ('equity','etf')")
               .get("symbol", []))
    watch = set(config.get("equities.watchlist", [])) | held
    min_cap = float(config.get("equities.earnings_min_market_cap", 5e10))
    rows = []
    d = date.today()
    for i in range(21):
        day = d + timedelta(days=i)
        if day.weekday() >= 5:
            continue
        try:
            data = get_json("https://api.nasdaq.com/api/calendar/earnings", {"date": day.isoformat()},
                            headers=NASDAQ_HEADERS)
        except Exception:  # noqa: BLE001
            continue
        for r in ((data.get("data") or {}).get("rows") or []):
            sym = r.get("symbol", "")
            cap = float(re.sub(r"[^\d.]", "", r.get("marketCap") or "") or 0)
            if sym in watch or cap >= min_cap:
                tag = "HELD" if sym in held else ("watch" if sym in watch else "")
                timing = {"time-pre-market": "BMO", "time-after-hours": "AMC"}.get(r.get("time", ""), "")
                rows.append({"date": day, "kind": "earnings", "name": f"{sym} earnings",
                             "detail": " ".join(x for x in [timing, f"EPS est {r.get('epsForecast','')}", tag] if x),
                             "source": "nasdaq"})
    store.execute("DELETE FROM calendar WHERE source = 'nasdaq'")
    return store.insert_df("calendar", pd.DataFrame(rows)) if rows else 0


# ------------------------------------------------------------------ Short interest
def run_short_interest(store: Store) -> int:
    syms = set(store.query("SELECT DISTINCT symbol FROM positions WHERE asset_class = 'equity'").get("symbol", []))
    syms |= set(config.get("equities.watchlist", []))
    rows = []
    for s in sorted(syms):
        try:
            data = get_json(f"https://api.nasdaq.com/api/quote/{s}/short-interest",
                            {"assetClass": "stocks"}, headers=NASDAQ_HEADERS)
            table = (((data.get("data") or {}).get("shortInterestTable") or {}).get("rows")) or []
        except Exception:  # noqa: BLE001
            continue
        for r in table[:6]:
            num = lambda x: float(re.sub(r"[^\d.]", "", str(x)) or 0)  # noqa: E731
            rows.append({"symbol": s, "settlement_date": pd.to_datetime(r["settlementDate"]).date(),
                         "short_interest": num(r.get("interest")), "avg_daily_volume": num(r.get("avgDailyShareVolume")),
                         "days_to_cover": num(r.get("daysToCover"))})
    return store.insert_df("short_interest", pd.DataFrame(rows), ["symbol", "settlement_date"]) if rows else 0


# ------------------------------------------------------------------ 13F
def _sec_headers() -> dict:
    ua = config.env("SEC_USER_AGENT")
    if not ua:
        raise RuntimeError("SEC_USER_AGENT not set (EDGAR requires 'Name email')")
    return {"User-Agent": ua, "Accept-Encoding": "gzip, deflate"}


def run_13f(store: Store) -> int:
    h = _sec_headers()
    n = 0
    for cik, fund in config.get("sec_13f_filers", {}).items():
        cik10 = cik.zfill(10)
        sub = get_json(f"https://data.sec.gov/submissions/CIK{cik10}.json", headers=h)
        recent = sub.get("filings", {}).get("recent", {})
        idx = next((i for i, f in enumerate(recent.get("form", [])) if f == "13F-HR"), None)
        if idx is None:
            continue
        acc = recent["accessionNumber"][idx].replace("-", "")
        period = recent.get("reportDate", [None] * (idx + 1))[idx]
        base = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}"
        files = get_json(f"{base}/index.json", headers=h).get("directory", {}).get("item", [])
        xml_name = next((f["name"] for f in files if f["name"].endswith(".xml") and "primary_doc" not in f["name"]), None)
        if not xml_name:
            continue
        with client(headers=h) as c:
            root = ET.fromstring(c.get(f"{base}/{xml_name}").content)
        ns = {"n": root.tag.split("}")[0].strip("{")} if root.tag.startswith("{") else {}
        q = (lambda e, t: e.find(f"n:{t}", ns)) if ns else (lambda e, t: e.find(t))
        agg: dict[str, dict] = {}
        for it in root.iter(f"{{{ns['n']}}}infoTable" if ns else "infoTable"):
            cusip = (q(it, "cusip").text or "").strip()
            amt = q(it, "shrsOrPrnAmt")
            rec = agg.setdefault(cusip, {"issuer": (q(it, "nameOfIssuer").text or "").strip(), "value": 0.0, "shares": 0.0})
            rec["value"] += float(q(it, "value").text or 0)
            sh = q(amt, "sshPrnamt") if amt is not None else None
            rec["shares"] += float(sh.text) if sh is not None and sh.text else 0.0
        df = pd.DataFrame([{"cik": cik, "fund": fund, "period": period, "issuer": v["issuer"], "cusip": k,
                            "value_usd": v["value"], "shares": v["shares"]} for k, v in agg.items()])
        if df.empty:
            continue
        df["period"] = pd.to_datetime(df["period"]).dt.date
        store.execute("DELETE FROM holdings_13f WHERE cik = ?", [cik])
        n += store.insert_df("holdings_13f", df)
    return n
