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


def test_tradingview_parse_and_record(store):
    from desk import integrations
    j = integrations.parse_tradingview(b'{"ticker": "NASDAQ:NVDA", "action": "BUY", "close": "141.2", "message": "breakout"}')
    assert (j["symbol"], j["action"], j["price"]) == ("NVDA", "buy", 141.2)
    t = integrations.parse_tradingview(b"SOL crossed 240")
    assert t["symbol"] == "SOL" and t["message"] == "SOL crossed 240"
    r = integrations.record_tradingview(store, b'{"symbol":"BYBIT:HYPEUSDT.P","action":"alert","idea":true,"message":"x"}')
    assert r["parsed"]["symbol"] == "HYPE"
    assert any(i["symbol"] == "HYPE" for i in store.records("SELECT * FROM ideas"))


def test_marketsurge_import_and_leaders(store):
    from desk import integrations
    csv_text = "Symbol\tCompany Name\tComposite Rating\tEPS Rating\tRS Rating\tAcc/Dis Rating\tPivot\tBase Pattern\n" \
               "MSFT\tMicrosoft\t95\t90\t88\tB+\t$1.00\tFlat base\nbad row!!\t\t\t\t\t\t\t\n"
    r = integrations.import_marketsurge(store, csv_text, "test")
    assert r["ok"] and r["rows"] == 1
    m = next(l for l in integrations.leaders(store) if l["symbol"] == "MSFT")
    assert m["composite"] == 95 and m["rs"] == 88 and m["acc_dis"] == "B+" and m["zone"] == "extended"
    assert integrations.set_outlook(store, "Market in correction", 20)["ok"]
    sig = regime.regime(store)["signals"][0]
    assert sig["name"] == "IBD market outlook" and sig["status"] == "red"


def test_coinalyze_with_mocked_api(monkeypatch):
    import time as _t
    from desk.sources import coinalyze
    from desk.analytics import crypto as cr

    s = Store(":memory:")
    monkeypatch.setenv("COINALYZE_API_KEY", "x")
    now = int(_t.time())
    markets = [
        {"symbol": "BTCUSDT_PERP.A", "exchange": "A", "base_asset": "BTC", "quote_asset": "USDT", "is_perpetual": True},
        {"symbol": "BTCUSD_PERP.H", "exchange": "H", "base_asset": "BTC", "quote_asset": "USD", "is_perpetual": True},
        {"symbol": "BTCUSD_PERP.A", "exchange": "A", "base_asset": "BTC", "quote_asset": "USD", "is_perpetual": True},
        {"symbol": "DOGEUSDT_PERP.A", "exchange": "A", "base_asset": "DOGE", "quote_asset": "USDT", "is_perpetual": True},
        {"symbol": "BTCUSDT.A", "exchange": "A", "base_asset": "BTC", "quote_asset": "USDT", "is_perpetual": False},
    ]
    data = {
        "exchanges": [{"code": "A", "name": "Binance"}, {"code": "H", "name": "Hyperliquid"}],
        "future-markets": markets,
        "open-interest": [{"symbol": "BTCUSDT_PERP.A", "value": 6e9}, {"symbol": "BTCUSD_PERP.H", "value": 2e9}],
        "funding-rate": [{"symbol": "BTCUSDT_PERP.A", "value": 0.01}, {"symbol": "BTCUSD_PERP.H", "value": 0.00125}],
        "predicted-funding-rate": [{"symbol": "BTCUSDT_PERP.A", "value": 0.012}],
        "liquidation-history": [{"symbol": "BTCUSDT_PERP.A", "history": [{"t": now - 3600, "l": 5e6, "s": 1e6}]}],
    }
    monkeypatch.setattr(coinalyze, "_get", lambda path, params=None, cost=1: data[path])
    monkeypatch.setattr(coinalyze, "coins", lambda store: ["BTC"])
    picked = coinalyze.markets(s)
    assert {m["symbol"] for m in picked} == {"BTCUSDT_PERP.A", "BTCUSD_PERP.H"}  # USDT preferred, spot/other coins excluded
    assert coinalyze.run(s) == 2
    x = cr.cross_venue(s, "BTC")[0]
    assert x["oi_usd"] == 8e9 and x["hyperliquid_share"] == 25.0
    # Binance 0.01%/8h -> 10.95%/yr ; Hyperliquid 0.00125%/1h -> 10.95%/yr
    assert x["funding_ann_oiw"] == pytest.approx(10.95, abs=0.01)
    assert x["liq_long_24h"] == 5e6 and x["liq_skew"] == "longs flushed"


def test_hermes_plugin_registers():
    import importlib.util
    from pathlib import Path
    import yaml
    root = Path(__file__).resolve().parent.parent / "hermes" / "desk-plugin"
    spec = importlib.util.spec_from_file_location("deskplugin", root / "__init__.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)

    class Ctx:
        tools, skills = {}, {}
        def register_tool(self, name, toolset, schema, handler): self.tools[name] = schema
        def register_skill(self, name, path): self.skills[name] = path

    c = Ctx()
    m.register(c)
    assert set(c.tools) == set(yaml.safe_load(open(root / "plugin.yaml"))["provides_tools"])
    assert set(c.skills) == {"desk-morning-brief", "desk-regime-watch", "desk-risk-check"}
    assert all(s["parameters"]["type"] == "object" for s in c.tools.values())
