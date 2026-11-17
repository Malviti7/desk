import { useState } from "react";
import { api, useApi } from "../api";
import { Card, Chg, Status, Table } from "../components/ui";
import { ChartCfg, msLink, openChart, toTV, TVChart } from "../components/TVChart";
import { num } from "../fmt";

const OUTLOOKS: [string, string][] = [
  ["confirmed_uptrend", "Confirmed uptrend"], ["uptrend_under_pressure", "Uptrend under pressure"],
  ["rally_attempt", "Rally attempt"], ["market_in_correction", "Market in correction"],
];

function OutlookCard() {
  const { data: o, reload } = useApi<any>("/marketsurge/outlook", 300);
  const [status, setStatus] = useState("confirmed_uptrend");
  const [exp, setExp] = useState("");
  const save = async () => { await api("/marketsurge/outlook", { method: "PUT", body: JSON.stringify({ status, exposure_pct: exp ? +exp : null }) }); reload(); };
  return (
    <Card title="IBD market outlook" right={o ? `set ${o.ts?.slice(0, 16).replace("T", " ")} UTC by ${o.set_by}` : "not set"}>
      {o ? <div style={{ fontSize: 18, marginBottom: 10 }}><Status status={o.color} label={o.label} />{o.exposure_pct != null && <span className="secondary"> · exposure {o.exposure_pct}%</span>}</div>
        : <div className="muted" style={{ marginBottom: 10 }}>Set it from MarketSurge's market pulse. It becomes the first regime signal.</div>}
      <div className="row">
        <select value={status} onChange={(e) => setStatus(e.target.value)}>{OUTLOOKS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
        <input placeholder="Exposure %" value={exp} onChange={(e) => setExp(e.target.value)} style={{ width: 100 }} />
        <button className="btn primary" onClick={save}>Update</button>
      </div>
    </Card>
  );
}

function ImportCard({ onDone }: { onDone: () => void }) {
  const [text, setText] = useState("");
  const [name, setName] = useState("MarketSurge");
  const [res, setRes] = useState<any>(null);
  const run = async () => { const r = await api("/marketsurge/import", { method: "POST", body: JSON.stringify({ csv: text, list_name: name }) }); setRes(r); if (r.ok) { setText(""); onDone(); } };
  const file = (f?: File) => f && f.text().then(setText);
  return (
    <Card title="Import from MarketSurge" right="CSV export, or copy a table and paste">
      <textarea value={text} onChange={(e) => setText(e.target.value)} rows={5} placeholder={"Symbol, Composite Rating, EPS Rating, RS Rating, Acc/Dis, Pivot, Pattern…"}
        style={{ width: "100%", background: "var(--surface-2)", color: "var(--text-primary)", border: "1px solid var(--border)", borderRadius: 6, padding: 8, fontFamily: "var(--mono)", fontSize: 12 }} />
      <div className="row" style={{ marginTop: 8 }}>
        <input type="file" accept=".csv,.txt,.tsv" onChange={(e) => file(e.target.files?.[0])} />
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="List name" style={{ width: 160 }} />
        <button className="btn primary" disabled={!text} onClick={run}>Import</button>
        {res && (res.ok ? <span className="pos">Imported {res.rows} · mapped {Object.values(res.columns_mapped).join(", ")}</span> : <span className="neg">{res.error}</span>)}
      </div>
    </Card>
  );
}

export default function Leaders() {
  const { data: leaders, reload } = useApi<any[]>("/leaders", 120);
  const { data: tv } = useApi<any[]>("/tradingview/alerts?limit=40", 30);
  const { data: cfg } = useApi<ChartCfg>("/charts/config", 600);
  const { data: hook } = useApi<any>("/config/webhook", 600);
  const [sel, setSel] = useState<string | null>(null);
  const current = sel || leaders?.[0]?.symbol;
  return (
    <div className="page">
      <div className="grid g2">
        <OutlookCard />
        <ImportCard onDone={reload} />
      </div>
      <div className="grid" style={{ gridTemplateColumns: "minmax(0, 1.15fr) minmax(0, 1fr)" }}>
        <Card title="Leaders" right="click a row to chart · ★ = held">
          <Table rows={leaders || []} empty="Import a MarketSurge screen above" cols={[
            { key: "symbol", label: "", left: true, render: (r) => <a style={{ cursor: "pointer" }} onClick={() => setSel(r.symbol)}><b>{r.symbol}</b>{r.held ? " ★" : ""}</a> },
            { key: "composite", label: "Comp", render: (r) => <span className="num">{num(r.composite, 0)}</span> },
            { key: "eps_rating", label: "EPS", render: (r) => <span className="num">{num(r.eps_rating, 0)}</span> },
            { key: "rs", label: "RS", render: (r) => <span className="num">{num(r.rs, 0)}</span> },
            { key: "acc_dis", label: "A/D", render: (r) => <span className="num">{r.acc_dis ?? "–"}</span> },
            { key: "group_rank", label: "Grp", render: (r) => <span className="num">{num(r.group_rank, 0)}</span> },
            { key: "pattern", label: "Base", left: true, render: (r) => <span className="secondary">{r.pattern ?? "–"}</span> },
            { key: "buy_point", label: "Buy pt", render: (r) => <span className="num">{num(r.buy_point)}</span> },
            { key: "live_price", label: "Price", render: (r) => <span className="num">{num(r.live_price)}</span> },
            { key: "dist_to_buy_pct", label: "From BP", render: (r) => <Chg v={r.dist_to_buy_pct} d={1} /> },
            { key: "zone", label: "", render: (r) => r.zone ? <span className={`pill ${r.zone === "buy zone" ? "book" : r.zone === "extended" ? "hot" : ""}`}>{r.zone}</span> : null },
            { key: "x", label: "", render: (r) => <a className="btn" onClick={() => openChart(r.symbol)}>⤢</a> },
          ]} />
        </Card>
        <Card title={current ? `${current} · TradingView` : "Chart"} right={current && <a className="btn" href={msLink(current, cfg)} target="_blank" rel="noreferrer">MarketSurge ↗</a>}>
          {current ? <TVChart tvSymbol={toTV(current, false, cfg)} height={460} studies={cfg?.studies || []} /> : <div className="empty">No leaders yet</div>}
        </Card>
      </div>
      <Card title="TradingView alerts" right={hook?.configured ? "webhook ready" : "set TV_WEBHOOK_SECRET in .env to enable"}>
        <Table rows={tv || []} empty="No TradingView alerts yet" cols={[
          { key: "ts", label: "Time (UTC)", left: true, render: (r) => <span className="num muted">{r.ts?.slice(5, 16).replace("T", " ")}</span> },
          { key: "symbol", label: "Symbol", left: true, render: (r) => r.symbol ? <a style={{ cursor: "pointer" }} onClick={() => openChart(r.symbol)}><b>{r.symbol}</b></a> : "–" },
          { key: "action", label: "Action", left: true, render: (r) => r.action ? <span className="pill">{r.action}</span> : null },
          { key: "price", label: "Price", render: (r) => <span className="num">{num(r.price)}</span> },
          { key: "interval", label: "TF", render: (r) => <span className="muted">{r.interval ?? ""}</span> },
          { key: "message", label: "Message", left: true, render: (r) => <span style={{ whiteSpace: "normal" }}>{r.message}</span> },
        ]} />
        <div className="muted" style={{ fontSize: 11, marginTop: 10 }}>
          Webhook URL for TradingView alerts: <span className="num">https://&lt;your-tunnel-host&gt;{hook?.path}</span>. Message body (JSON):{" "}
          <span className="num">{'{"symbol":"{{ticker}}","action":"buy","price":{{close}},"interval":"{{interval}}","message":"Breakout"}'}</span>
        </div>
      </Card>
    </div>
  );
}
