import { useState } from "react";
import { api, useApi } from "../api";
import { Card, LineViz, Loading, Table, Tile } from "../components/ui";
import { openChart } from "../components/TVChart";
import { days, fixed, money, num, sign } from "../fmt";

function ThesisEditor({ symbols, onSaved }: { symbols: string[]; onSaved: () => void }) {
  const [f, setF] = useState<any>({ symbol: symbols[0] || "", direction: "long", thesis: "", stop: "", target: "", catalyst: "", catalyst_date: "" });
  const set = (k: string) => (e: any) => setF({ ...f, [k]: e.target.value });
  const save = async () => {
    await api("/theses", { method: "PUT", body: JSON.stringify({
      ...f, stop: f.stop ? +f.stop : null, target: f.target ? +f.target : null, catalyst_date: f.catalyst_date || null, catalyst: f.catalyst || null,
    }) });
    onSaved();
  };
  return (
    <div className="form-grid">
      <label>Symbol<input list="syms" value={f.symbol} onChange={set("symbol")} /></label>
      <datalist id="syms">{symbols.map((s) => <option key={s} value={s} />)}</datalist>
      <label>Direction<select value={f.direction} onChange={set("direction")}><option>long</option><option>short</option></select></label>
      <label>Stop<input value={f.stop} onChange={set("stop")} inputMode="decimal" /></label>
      <label>Target<input value={f.target} onChange={set("target")} inputMode="decimal" /></label>
      <label>Catalyst<input value={f.catalyst} onChange={set("catalyst")} /></label>
      <label>Catalyst date<input type="date" value={f.catalyst_date} onChange={set("catalyst_date")} /></label>
      <label style={{ gridColumn: "1 / -1" }}>Thesis<input value={f.thesis} onChange={set("thesis")} placeholder="Why you own it, and what would prove you wrong" /></label>
      <div><button className="btn primary" onClick={save}>Save thesis</button></div>
    </div>
  );
}

export default function Portfolio() {
  const { data: p, error, reload } = useApi("/portfolio", 30);
  if (!p) return <Loading error={error} />;
  const ex = p.exposures || {};
  const hl = p.hyperliquid;
  const symbols = Array.from(new Set((p.positions || []).map((x: any) => x.symbol))) as string[];
  const eqHist = (hl?.equity_history || []).map((r: any) => ({ ts: r.ts.slice(5, 13), equity: r.equity }));
  return (
    <div className="page">
      <div className="grid g4">
        <Tile label="1d P&L" value={money(p.pnl_1d_total)} cls={sign(p.pnl_1d_total)} sub={`Unrealized ${money(p.unrealized_total)}`} />
        <Tile label="Gross" value={money(ex.gross)} sub={`Long ${money(ex.long)} · Short ${money(ex.short)}`} />
        <Tile label="Net" value={money(ex.net)} sub={`Cash ${money(ex.cash)}`} />
        <Tile label="Concentration" value={`${num(ex.top5_pct_gross, 0)}%`} sub={`top 5 of gross · ${num(ex.effective_positions, 1)} effective positions`} />
      </div>
      <Card title="Positions" right="all accounts">
        <Table rows={p.positions} cols={[
          { key: "symbol", label: "", left: true, render: (r) => r.asset_class === "cash" ? <b>{r.symbol}</b> : <a style={{ cursor: "pointer" }} title="Open chart" onClick={() => openChart(r.symbol, r.asset_class.startsWith("crypto"))}><b>{r.symbol}</b> ⤢</a> },
          { key: "account", label: "Acct", left: true, render: (r) => <span className="muted">{r.account}</span> },
          { key: "asset_class", label: "Type", left: true, render: (r) => <span className="pill">{r.asset_class.replace("crypto_", "")}</span> },
          { key: "qty", label: "Qty", render: (r) => <span className="num">{num(r.qty)}</span> },
          { key: "price", label: "Price", render: (r) => <span className="num">{num(r.price)}</span> },
          { key: "notional", label: "Notional", render: (r) => <span className="num">{money(r.notional)}</span> },
          { key: "pct_gross", label: "% gross", render: (r) => <span className="num">{r.pct_gross == null ? "–" : `${r.pct_gross.toFixed(1)}%`}</span> },
          { key: "pnl_1d", label: "1d P&L", render: (r) => <span className={`num ${sign(r.pnl_1d)}`}>{money(r.pnl_1d)}</span> },
          { key: "unrealized_pnl", label: "Unreal.", render: (r) => <span className={`num ${sign(r.unrealized_pnl)}`}>{money(r.unrealized_pnl)}</span> },
          { key: "beta_spx", label: "β SPX", render: (r) => <span className="num">{fixed(r.beta_spx)}</span> },
          { key: "beta_btc", label: "β BTC", render: (r) => <span className="num">{fixed(r.beta_btc)}</span> },
          { key: "days_to_exit", label: "Days out", render: (r) => <span className="num">{days(r.days_to_exit)}</span> },
          { key: "dist_to_stop_pct", label: "To stop", render: (r) => <span className={`num ${r.stop_breached ? "neg" : ""}`}>{r.dist_to_stop_pct == null ? "–" : `${r.dist_to_stop_pct.toFixed(1)}%`}</span> },
          { key: "dist_to_target_pct", label: "To target", render: (r) => <span className="num">{r.dist_to_target_pct == null ? "–" : `${r.dist_to_target_pct.toFixed(1)}%`}</span> },
        ]} />
      </Card>
      {hl && (
        <div className="grid g2">
          <Card title="Hyperliquid account" right={`as of ${hl.as_of?.slice(0, 16)}`}>
            <div className="grid g2">
              <div><div className="muted">Account value</div><div className="num" style={{ fontSize: 18 }}>{money(hl.account_value)}</div></div>
              <div><div className="muted">Maintenance margin</div><div className="num" style={{ fontSize: 18 }}>{money(hl.maint_margin)}</div></div>
              <div><div className="muted">Protected spot ({hl.protected?.join(", ")})</div><div className="num" style={{ fontSize: 18 }}>{money(hl.protected_spot_value)}</div></div>
              <div><div className="muted">Buffer before protected spot</div><div className={`num ${hl.buffer_before_protected < 0 ? "neg" : "pos"}`} style={{ fontSize: 18 }}>{money(hl.buffer_before_protected)}</div></div>
              <div><div className="muted">Perp gross / net</div><div className="num">{money(hl.perp_gross)} / {money(hl.perp_net)}</div></div>
              <div><div className="muted">Leverage on free equity</div><div className="num">{num(hl.leverage_on_free_equity, 2)}x</div></div>
            </div>
            <h3 style={{ marginTop: 14 }}>Liquidation distance</h3>
            <Table rows={hl.liquidation_distances} empty="No perps" cols={[
              { key: "symbol", label: "", left: true },
              { key: "price", label: "Price", render: (r) => <span className="num">{num(r.price)}</span> },
              { key: "liquidation_px", label: "Liq px", render: (r) => <span className="num">{num(r.liquidation_px)}</span> },
              { key: "distance_pct", label: "Distance", render: (r) => <span className="num">{r.distance_pct.toFixed(1)}%</span> },
            ]} />
          </Card>
          <Card title="Hyperliquid equity" right={hl.drawdown_30d_pct != null ? `30d drawdown ${hl.drawdown_30d_pct.toFixed(1)}%` : ""}>
            <LineViz data={eqHist} x="ts" series={[{ key: "equity", name: "Equity" }]} height={280} fmt={(v) => money(v)} />
          </Card>
        </div>
      )}
      <div className="grid g2">
        <Card title="Exposure by asset class">
          <Table rows={ex.by_asset_class || []} cols={[
            { key: "asset_class", label: "", left: true },
            { key: "gross", label: "Gross", render: (r) => <span className="num">{money(r.gross)}</span> },
            { key: "net", label: "Net", render: (r) => <span className="num">{money(r.net)}</span> },
          ]} />
        </Card>
        <Card title="Exposure by account">
          <Table rows={ex.by_account || []} cols={[
            { key: "account", label: "", left: true },
            { key: "gross", label: "Gross", render: (r) => <span className="num">{money(r.gross)}</span> },
            { key: "net", label: "Net", render: (r) => <span className="num">{money(r.net)}</span> },
          ]} />
        </Card>
      </div>
      <Card title="Theses" right="every position should have one">
        <Table rows={(p.positions || []).filter((x: any) => x.thesis)} empty="No theses yet" cols={[
          { key: "symbol", label: "", left: true, render: (r) => <b>{r.symbol}</b> },
          { key: "thesis", label: "Thesis", left: true, render: (r) => <span style={{ whiteSpace: "normal" }}>{r.thesis}</span> },
          { key: "stop", label: "Stop", render: (r) => <span className="num">{num(r.stop)}</span> },
          { key: "target", label: "Target", render: (r) => <span className="num">{num(r.target)}</span> },
          { key: "catalyst", label: "Catalyst", left: true, render: (r) => <span className="secondary">{r.catalyst} {r.catalyst_date}</span> },
        ]} />
        <h3 style={{ marginTop: 16 }}>Add / update</h3>
        <ThesisEditor symbols={symbols} onSaved={reload} />
      </Card>
    </div>
  );
}
