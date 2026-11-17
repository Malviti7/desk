import { useState } from "react";
import { api, useApi } from "../api";
import { Card, Loading, Table } from "../components/ui";
import { num } from "../fmt";
import { AlertList, CalendarList, NewsList } from "./Morning";

export function News() {
  const [q, setQ] = useState("");
  const [bookOnly, setBookOnly] = useState(false);
  const { data: news } = useApi<any[]>(`/news?limit=100&book_only=${bookOnly}${q ? `&q=${encodeURIComponent(q)}` : ""}`, 120);
  const { data: cal } = useApi<any[]>("/calendar?days=30", 600);
  const { data: alerts } = useApi<any[]>("/alerts?hours=168", 60);
  return (
    <div className="page">
      <div className="grid g2">
        <Card title="Headlines" right={
          <span className="row">
            <input placeholder="filter: fed, $BTC, tariffs…" value={q} onChange={(e) => setQ(e.target.value)} />
            <label className="secondary"><input type="checkbox" checked={bookOnly} onChange={(e) => setBookOnly(e.target.checked)} /> my book only</label>
          </span>}>
          {news ? <NewsList items={news} /> : <Loading />}
        </Card>
        <div className="grid">
          <Card title="Calendar" right="next 30 days">{cal ? <CalendarList items={cal} /> : <Loading />}</Card>
          <Card title="Alerts" right="last 7 days">{alerts ? <AlertList alerts={alerts} /> : <Loading />}</Card>
        </div>
      </div>
    </div>
  );
}

export function Ideas() {
  const [status, setStatus] = useState("open");
  const { data: ideas, reload } = useApi<any[]>(`/ideas${status ? `?status=${status}` : ""}`, 60);
  const [f, setF] = useState({ symbol: "", direction: "long", trigger_px: "", trigger_dir: "below", note: "" });
  const add = async () => {
    if (!f.symbol) return;
    await api("/ideas", { method: "POST", body: JSON.stringify({ ...f, trigger_px: f.trigger_px ? +f.trigger_px : null }) });
    setF({ ...f, symbol: "", trigger_px: "", note: "" });
    reload();
  };
  const close = async (id: number) => { await api(`/ideas/${id}`, { method: "DELETE" }); reload(); };
  return (
    <div className="page">
      <Card title="Add idea" right="price triggers fire an alert">
        <div className="row">
          <input placeholder="Symbol" value={f.symbol} onChange={(e) => setF({ ...f, symbol: e.target.value.toUpperCase() })} style={{ width: 90 }} />
          <select value={f.direction} onChange={(e) => setF({ ...f, direction: e.target.value })}><option>long</option><option>short</option><option>hedge</option></select>
          <select value={f.trigger_dir} onChange={(e) => setF({ ...f, trigger_dir: e.target.value })}><option value="below">trigger below</option><option value="above">trigger above</option></select>
          <input placeholder="Price" value={f.trigger_px} onChange={(e) => setF({ ...f, trigger_px: e.target.value })} style={{ width: 90 }} />
          <input placeholder="What would make you act" value={f.note} onChange={(e) => setF({ ...f, note: e.target.value })} style={{ flex: 1, minWidth: 220 }} />
          <button className="btn primary" onClick={add}>Add</button>
        </div>
      </Card>
      <Card title="Pipeline" right={
        <select value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="open">open</option><option value="triggered">triggered</option><option value="closed">closed</option><option value="">all</option>
        </select>}>
        <Table rows={ideas || []} empty="No ideas" cols={[
          { key: "symbol", label: "", left: true, render: (r) => <b>{r.symbol}</b> },
          { key: "direction", label: "Side", left: true },
          { key: "trigger_px", label: "Trigger", render: (r) => <span className="num">{r.trigger_px ? `${r.trigger_dir} ${num(r.trigger_px)}` : "–"}</span> },
          { key: "note", label: "Note", left: true, render: (r) => <span style={{ whiteSpace: "normal" }}>{r.note}</span> },
          { key: "created_by", label: "By", left: true, render: (r) => <span className="muted">{r.created_by}</span> },
          { key: "status", label: "Status", left: true, render: (r) => <span className="pill">{r.status}</span> },
          { key: "x", label: "", render: (r) => r.status !== "closed" ? <button className="btn" onClick={() => close(r.id)}>Close</button> : null },
        ]} />
      </Card>
    </div>
  );
}

export function Data() {
  const { data: st, reload } = useApi<any[]>("/ingest/status", 30);
  const [busy, setBusy] = useState<string | null>(null);
  const run = async (job: string) => { setBusy(job); try { await api(`/ingest/${job}`, { method: "POST" }); } finally { setBusy(null); reload(); } };
  return (
    <div className="page">
      <Card title="Data jobs" right={<button className="btn primary" disabled={!!busy} onClick={() => run("all")}>{busy === "all" ? "Refreshing…" : "Refresh all"}</button>}>
        <Table rows={st || []} cols={[
          { key: "job", label: "Job", left: true, render: (r) => <b>{r.job}</b> },
          { key: "last_status", label: "Status", left: true, render: (r) => <span className={`status ${r.last_status === "ok" ? "green" : r.last_status === "skipped" ? "amber" : "red"}`}><span className="dot" />{r.last_status}</span> },
          { key: "last_run", label: "Last run (UTC)", left: true, render: (r) => <span className="num muted">{r.last_run?.slice(0, 16).replace("T", " ")}</span> },
          { key: "last_rows", label: "Rows", render: (r) => <span className="num">{r.last_rows}</span> },
          { key: "last_error", label: "Note", left: true, render: (r) => <span className="muted" style={{ whiteSpace: "normal" }}>{(r.last_error || "").split("\n")[0].slice(0, 120)}</span> },
          { key: "x", label: "", render: (r) => <button className="btn" disabled={!!busy} onClick={() => run(r.job)}>{busy === r.job ? "…" : "Run"}</button> },
        ]} />
      </Card>
    </div>
  );
}
