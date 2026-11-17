import { useApi } from "../api";
import { Card, Chg, Loading, Table } from "../components/ui";
import { fixed, money, num } from "../fmt";

const perfCols = [
  { key: "name", label: "", left: true, render: (r: any) => <span>{r.name} <span className="muted">{r.ticker}</span></span> },
  { key: "price", label: "Last", render: (r: any) => <span className="num">{num(r.price)}</span> },
  { key: "d1", label: "1d", render: (r: any) => <Chg v={r.d1} /> },
  { key: "w1", label: "1w", render: (r: any) => <Chg v={r.w1} /> },
  { key: "m1", label: "1m", render: (r: any) => <Chg v={r.m1} /> },
  { key: "ytd", label: "YTD", render: (r: any) => <Chg v={r.ytd} d={1} /> },
];

export default function Equities() {
  const { data: e, error } = useApi("/equities", 600);
  if (!e) return <Loading error={error} />;
  return (
    <div className="page">
      <div className="grid g2">
        <Card title="Sectors"><Table rows={e.sectors} cols={perfCols} initialSort="w1" /></Card>
        <div className="grid">
          <Card title="Indices"><Table rows={e.indices} cols={perfCols} /></Card>
          <Card title="Factors" right="style ETFs"><Table rows={e.factors} cols={perfCols} /></Card>
        </div>
      </div>
      <Card title="CFTC positioning" right="non-commercial net, weekly">
        <Table rows={e.cot} cols={[
          { key: "market", label: "", left: true },
          { key: "report_date", label: "As of", render: (r) => <span className="num muted">{r.report_date}</span> },
          { key: "net_spec", label: "Net spec", render: (r) => <span className="num">{num(r.net_spec, 0)}</span> },
          { key: "chg_1w", label: "1w chg", render: (r) => <span className="num">{num(r.chg_1w, 0)}</span> },
          { key: "net_pct_oi", label: "% of OI", render: (r) => <span className="num">{fixed(r.net_pct_oi, 1)}%</span> },
          { key: "pctile_3y", label: "3y %ile", render: (r) => <span className="num">{num(r.pctile_3y, 0)}</span> },
          { key: "signal", label: "", render: (r) => r.signal ? <span className="pill hot">{r.signal}</span> : null },
        ]} />
      </Card>
      <div className="grid g2">
        <Card title="Short interest" right="watchlist + holdings">
          <Table rows={e.short_interest} initialSort="dtc" cols={[
            { key: "symbol", label: "", left: true, render: (r) => <b>{r.symbol}</b> },
            { key: "si", label: "Short int", render: (r) => <span className="num">{num(r.si, 0)}</span> },
            { key: "dtc", label: "Days to cover", render: (r) => <span className="num">{fixed(r.dtc, 1)}</span> },
            { key: "as_of", label: "As of", render: (r) => <span className="num muted">{r.as_of}</span> },
          ]} />
        </Card>
        <Card title="13F crowding" right="most widely held across tracked funds">
          <Table rows={e.crowding_13f?.top_holdings || []} cols={[
            { key: "issuer", label: "", left: true },
            { key: "holders", label: "# funds", render: (r) => <span className="num">{r.holders}</span> },
            { key: "value_usd", label: "Value", render: (r) => <span className="num">{money(r.value_usd)}</span> },
          ]} />
          <div className="muted" style={{ marginTop: 8, fontSize: 11 }}>
            Filers: {(e.crowding_13f?.funds || []).map((f: any) => `${f.fund} (${f.period})`).join(" · ") || "none yet"}. 13Fs lag 45 days.
          </div>
        </Card>
      </div>
    </div>
  );
}
