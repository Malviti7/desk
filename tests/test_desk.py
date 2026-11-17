import pandas as pd
import pytest

from desk import alerts, demo
from desk.analytics import brief, crypto, positioning, regime, risk
from desk.analytics.common import change
from desk.store import Store, utcnow


@pytest.fixture(scope="module")
def store():
    s = Store(":memory:")
    demo.seed(s)
    return s


def test_change_units():
    s = pd.Series([4.00, 4.25], index=pd.to_datetime(["2026-01-01", "2026-01-09"]))
    assert change(s, 7, True) == pytest.approx(25.0)        # rates in bp
    assert change(s, 7, False) == pytest.approx(6.25)       # prices in %
    assert change(s, 7, "abs") == pytest.approx(0.25)       # correlations etc.


def test_regime_and_macro(store):
    r = regime.regime(store)
    assert r["label"] in {"Risk-on", "Neutral", "Caution", "Stress"}
    assert len(r["signals"]) >= 8
    m = regime.macro_snapshot(store)
    assert m["rates"] and m["liquidity"][0]["id"] == "calc:net_liquidity"


def test_crypto(store):
    c = crypto.snapshot(store)
    hype = next(p for p in c["perps"] if p["coin"] == "HYPE")
    assert hype["held"] and hype["crowding"] == "crowded long"


def test_portfolio_and_risk(store):
    p = risk.portfolio(store)
    assert p["exposures"]["gross"] > 0
    assert p["hyperliquid"]["protected"] == ["HYPE"]
    rpt = risk.report(store)
    assert rpt["var"]["var_99"] >= rpt["var"]["var_95"] > 0
    assert len(rpt["stress"]) == 6


def test_stress_math():
    s = Store(":memory:")
    now = utcnow()
    s.insert_df("positions", pd.DataFrame([
        {"ts": now, "account": "hyperliquid", "venue": "hyperliquid", "symbol": "HYPE", "asset_class": "crypto_spot",
         "qty": 1000, "entry_px": 10, "price": 20, "notional": 20000, "unrealized_pnl": None, "leverage": None,
         "liquidation_px": None, "margin_used": None, "price_source": "hyperliquid"},
        {"ts": now, "account": "hyperliquid", "venue": "hyperliquid", "symbol": "BTC", "asset_class": "crypto_perp",
         "qty": 1, "entry_px": 100000, "price": 100000, "notional": 100000, "unrealized_pnl": 0, "leverage": 10,
         "liquidation_px": 80000, "margin_used": 10000, "price_source": "hyperliquid"},
    ]))
    s.execute("INSERT INTO account_state VALUES (?, 'hyperliquid', 'hyperliquid', 30000, 3000, 10000, 0, '{}')", [now])
    # No price history: betas default to 1.0. BTC -10% -> perp -10k, HYPE -10% -> -2k
    out = risk.run_stress(s, {"name": "t", "btc": -0.10})
    assert out["total_pnl"] == pytest.approx(-12000)
    hl = out["hyperliquid"]
    assert hl["equity_after"] == pytest.approx(18000)
    assert hl["maint_after"] == pytest.approx(2700)       # scaled with perp notional
    # buffer = equity after (18k) - protected spot after (18k) - maint (2.7k) < 0
    assert hl["protected_spot_at_risk"] is True


def test_brief_and_alerts(store):
    b = brief.build(store)
    assert b["regime"] and b["calendar"] and "Regime" in brief.to_markdown(b)
    assert alerts.run(store) >= 1
    assert alerts.run(store) == 0  # deduped


def test_positioning(store):
    p = positioning.snapshot(store)
    assert p["cot"] and p["sectors"] and p["crowding_13f"]["top_holdings"]


def test_what_if(store):
    base = risk.run_stress(store, {"btc": -0.2})
    more = risk.run_stress(store, {"btc": -0.2, "add": [{"symbol": "SOL", "notional": 50000}]})
    assert more["total_pnl"] < base["total_pnl"]
    assert any(p["symbol"] == "SOL" and p["notional"] == 50000 for p in more["positions"])
