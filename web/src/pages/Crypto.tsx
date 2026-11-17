import { useState } from "react";
import { useApi } from "../api";
import { Card, Chg, IndicatorTable, LineViz, Loading, Table, Tile } from "../components/ui";
import { fixed, money, num, sign } from "../fmt";

export default function Crypto() {
  const { data: c, error } = useApi("/crypto", 60);
  const [coin, setCoin] = useState("BTC");
  const { data: fh } = useApi<any[]>(`/crypto/funding/${coin}?days=14`, 300);
  if (!c) return <Loading error={error} />;
  const dvol = (c.implied_vol || [])[0];
  const stable = (c.flows || []).find((f: any) => f.id === "llama:stablecoin_supply");
  const series = (fh || []).map((r) => ({ ...r, ts: r.ts.slice(5, 13).replace("T", " ") }));
  return (
    <div className="page">
      <div className="grid g4">
        <Tile label="Total perp OI tracked" value={money(c.total_oi_usd)} sub="Hyperliquid" />
        <Tile label="OI-weighted funding" value={`${num(c.oi_weighted_funding_ann, 1)}%`} sub="annualized" />
        <Tile label={dvol?.name ?? "DVOL"} value={num(dvol?.value, 1)} sub={<>1w <Chg v={dvol?.chg_1w} /></>} />
        <Tile label="Stablecoin supply" value={money(stable?.value)} sub={<>1m <Chg v={stable?.chg_1m} /></>} />
      </div>
      <Card title="Perps" right="click a row to chart funding · • = held">
        <Table rows={c.perps} initialSort="oi_usd" cols={[
          { key: "coin", label: "", left: true, render: (r) => <a onClick={() => setCoin(r.coin)} style={{ cursor: "pointer" }}><b>{r.coin}</b>{r.held ? " •" : ""}</a> },
          { key: "mark", label: "Mark", render: (r) => <span className="num">{num(r.mark)}</span> },
          { key: "chg_24h", label: "24h", render: (r) => <Chg v={r.chg_24h} /> },
          { key: "funding_ann", label: "Funding (ann)", render: (r) => <span className={`num ${sign(r.funding_ann)}`}>{num(r.funding_ann, 1)}%</span> },
          { key: "oi_usd", label: "OI", render: (r) => <span className="num">{money(r.oi_usd)}</span> },
          { key: "oi_chg_24h", label: "OI 24h", render: (r) => <Chg v={r.oi_chg_24h} /> },
          { key: "volume_24h", label: "Vol 24h", render: (r) => <span className="num">{money(r.volume_24h)}</span> },
          { key: "premium_bps", label: "Premium", render: (r) => <span className="num">{fixed(r.premium_bps, 1)}bp</span> },
          { key: "crowding", label: "", render: (r) => r.crowding ? <span className="pill hot">{r.crowding}</span> : null },
        ]} />
      </Card>
      <div className="grid g2">
        <Card title={`${coin} funding, annualized %`} right="last 14d">
          <LineViz data={series} x="ts" series={[{ key: "funding_ann", name: "Funding" }]} zero fmt={(v) => `${v.toFixed(0)}%`} />
        </Card>
        <Card title={`${coin} open interest`} right="last 14d">
          <LineViz data={series} x="ts" series={[{ key: "oi_usd", name: "OI" }]} fmt={(v) => money(v)} />
        </Card>
      </div>
      <div className="grid g2">
        <Card title="Trend">
          <Table rows={c.trends} cols={[
            { key: "coin", label: "", left: true, render: (r) => <b>{r.coin}</b> },
            { key: "price", label: "Price", render: (r) => <span className="num">{num(r.price)}</span> },
            { key: "vs_ma20", label: "vs 20d", render: (r) => <Chg v={r.vs_ma20} d={1} /> },
            { key: "vs_ma50", label: "vs 50d", render: (r) => <Chg v={r.vs_ma50} d={1} /> },
            { key: "vs_ma200", label: "vs 200d", render: (r) => <Chg v={r.vs_ma200} d={1} /> },
            { key: "from_52w_high", label: "From high", render: (r) => <Chg v={r.from_52w_high} d={1} /> },
            { key: "rv_30d", label: "30d RV", render: (r) => <span className="num">{num(r.rv_30d, 0)}%</span> },
          ]} />
        </Card>
        <Card title="Implied vol & flows"><IndicatorTable rows={[...(c.implied_vol || []), ...(c.flows || [])]} /></Card>
      </div>
      <Card title="Crypto equities & ETFs"><IndicatorTable rows={c.crypto_equities} /></Card>
    </div>
  );
}
