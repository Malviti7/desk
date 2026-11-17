import { useEffect, useState } from "react";
import { api, useApi } from "../api";
import { Card, IndicatorTable, LineViz, Loading } from "../components/ui";
import { num } from "../fmt";

export function SeriesExplorer({ initial = "fred:DGS10" }: { initial?: string }) {
  const { data: catalog } = useApi<any[]>("/series", 600);
  const [id, setId] = useState(initial);
  const [days, setDays] = useState(365);
  const [s, setS] = useState<any>(null);
  useEffect(() => { api(`/series/${encodeURIComponent(id)}?days=${days}`).then(setS).catch(() => setS(null)); }, [id, days]);
  return (
    <Card title="Series explorer" right={
      <span className="row">
        <select value={id} onChange={(e) => setId(e.target.value)}>
          {(catalog || []).map((c) => <option key={c.series_id} value={c.series_id}>{c.category} · {c.name || c.series_id}</option>)}
        </select>
        <select value={days} onChange={(e) => setDays(+e.target.value)}>
          {[30, 90, 180, 365, 730].map((d) => <option key={d} value={d}>{d}d</option>)}
        </select>
      </span>}>
      {s ? (
        <>
          <div className="secondary" style={{ marginBottom: 6 }}>
            <b>{s.name}</b> <span className="num">{num(s.value)}</span> {s.unit} · 1y percentile {num(s.pctile_1y, 0)} · z {num(s.z_1y, 2)}
          </div>
          <LineViz data={s.points} x="date" series={[{ key: "value", name: s.name }]} height={240} />
        </>
      ) : <div className="empty">No data for this series</div>}
    </Card>
  );
}

export default function Macro() {
  const { data: m, error } = useApi("/macro", 300);
  if (!m) return <Loading error={error} />;
  const curve = (m.curve?.now || []).map((p: any, i: number) => ({ tenor: p.tenor, now: p.yield, month_ago: m.curve.month_ago?.[i]?.yield }));
  return (
    <div className="page">
      <div className="grid g2">
        <Card title="Treasury curve">
          <LineViz data={curve} x="tenor" series={[{ key: "now", name: "Today" }, { key: "month_ago", name: "1 month ago", color: "var(--text-muted)" }]} height={200} fmt={(v) => `${v.toFixed(2)}%`} />
        </Card>
        <Card title="Rates (changes in bp)"><IndicatorTable rows={m.rates} /></Card>
      </div>
      <div className="grid g2">
        <Card title="Liquidity"><IndicatorTable rows={m.liquidity} /></Card>
        <Card title="Credit"><IndicatorTable rows={m.credit} /></Card>
      </div>
      <div className="grid g2">
        <Card title="Volatility"><IndicatorTable rows={m.vol} /></Card>
        <Card title="FX"><IndicatorTable rows={m.fx} /></Card>
      </div>
      <div className="grid g2">
        <Card title="Futures & global indices"><IndicatorTable rows={[...(m.futures || []), ...(m.indices || [])]} /></Card>
        <Card title="Commodities"><IndicatorTable rows={m.commodities} /></Card>
      </div>
      <div className="grid g2">
        <Card title="Cross-asset correlations" right="do your hedges hedge?"><IndicatorTable rows={m.correlations} /></Card>
        <Card title="Economy"><IndicatorTable rows={m.economy} /></Card>
      </div>
      <SeriesExplorer />
    </div>
  );
}
