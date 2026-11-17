import { useState } from "react";
import { api, useApi } from "../api";
import { Card, DivBar, Loading, SignedBars, Table, Tile } from "../components/ui";
import { days, money, num, sign } from "../fmt";

function heat(v: number): string {
  // diverging blue (neg) <-> gray midpoint <-> red (pos), dark-surface steps
  const a = Math.min(Math.abs(v), 1);
  return v >= 0 ? `rgba(230, 103, 103, ${0.12 + a * 0.6})` : `rgba(57, 135, 229, ${0.12 + a * 0.6})`;
}

function CustomStress() {
  const [f, setF] = useState({ spx: "-10", btc: "-25", overrides: "HYPE:-40" });
  const [res, setRes] = useState<any>(null);
  const run = async () => {
    const overrides = Object.fromEntries(f.overrides.split(",").map((s) => s.split(":")).filter((p) => p.length === 2 && p[0].trim())
      .map(([k, v]) => [k.trim().toUpperCase(), +v / 100]));
    setRes(await api("/stress", { method: "POST", body: JSON.stringify({ name: "custom", spx: +f.spx / 100, btc: +f.btc / 100, overrides }) }));
  };
  const h = res?.hyperliquid;
  return (
    <Card title="Custom stress test">
      <div className="row">
        <label className="muted">SPX %<input style={{ width: 70, marginLeft: 6 }} value={f.spx} onChange={(e) => setF({ ...f, spx: e.target.value })} /></label>
        <label className="muted">BTC %<input style={{ width: 70, marginLeft: 6 }} value={f.btc} onChange={(e) => setF({ ...f, btc: e.target.value })} /></label>
        <label className="muted">Overrides<input style={{ width: 180, marginLeft: 6 }} value={f.overrides} onChange={(e) => setF({ ...f, overrides: e.target.value })} placeholder="HYPE:-40,SOL:-50" /></label>
        <button className="btn primary" onClick={run}>Run</button>
      </div>
      {res && (
        <div style={{ marginTop: 12 }}>
          <div className="row" style={{ gap: 24 }}>
            <div>Total P&L <span className={`num ${sign(res.total_pnl)}`} style={{ fontSize: 18 }}>{money(res.total_pnl)}</span></div>
            {h && <div>HL equity after <span className="num">{money(h.equity_after)}</span> · headroom <span className="num">{num(h.headroom_after_pct, 0)}%</span></div>}
            {h && <div className={h.protected_spot_at_risk ? "neg" : "pos"}>{h.protected_spot_at_risk ? "⚠ Protected spot at risk" : "✓ Protected spot safe"} ({money(h.buffer_before_protected_after)} buffer)</div>}
          </div>
          <Table rows={res.positions} cols={[
            { key: "symbol", label: "", left: true, render: (r) => <b>{r.symbol}</b> },
            { key: "account", label: "Acct", left: true, render: (r) => <span className="muted">{r.account}</span> },
            { key: "shock_pct", label: "Shock", render: (r) => <span className="num">{num(r.shock_pct, 1)}%</span> },
            { key: "pnl", label: "P&L", render: (r) => <span className={`num ${sign(r.pnl)}`}>{money(r.pnl)}</span> },
          ]} />
        </div>
      )}
    </Card>
  );
}

export default function Risk() {
  const { data: r, error } = useApi("/risk", 120);
  if (!r) return <Loading error={error} />;
  if (r.note) return <div className="page"><Card><div className="empty">{r.note}</div></Card></div>;
  const v = r.var || {};
  const maxStress = Math.max(...(r.stress || []).map((s: any) => Math.abs(s.total_pnl)), 1);
  const maxFac = Math.max(...(r.factor_exposures || []).map((f: any) => Math.abs(f.dollar_exposure)), 1);
  const corr = r.correlation || { symbols: [], matrix: [] };
  return (
    <div className="page">
      <div className="grid g4">
        <Tile label="1-day VaR 95%" value={money(v.var_95)} sub={`ES ${money(v.es_95)} · ${v.lookback_days ?? "–"}d history`} />
        <Tile label="1-day VaR 99%" value={money(v.var_99)} sub={`ES ${money(v.es_99)}`} />
        <Tile label="Worst historical day" value={money(v.worst_day)} sub={v.worst_day_date} />
        <Tile label="Worst stress" value={money(r.worst_stress?.total_pnl)} cls="neg" sub={r.worst_stress?.name} />
      </div>
      <div className="grid g2">
        <Card title="Stress scenarios" right="via beta to SPX / BTC">
          <Table rows={r.stress} cols={[
            { key: "name", label: "", left: true },
            { key: "total_pnl", label: "P&L", render: (s) => <span className={`num ${sign(s.total_pnl)}`}>{money(s.total_pnl)}</span> },
            { key: "bar", label: "", render: (s) => <DivBar v={s.total_pnl} max={maxStress} />, sort: (s) => s.total_pnl },
            { key: "hl", label: "HL headroom after", render: (s) => <span className="num">{s.hyperliquid ? `${num(s.hyperliquid.headroom_after_pct, 0)}%` : "–"}</span>, sort: (s) => s.hyperliquid?.headroom_after_pct },
            { key: "prot", label: "Protected spot", render: (s) => s.hyperliquid ? (s.hyperliquid.protected_spot_at_risk ? <span className="neg">⚠ at risk</span> : <span className="pos">✓ safe</span>) : "–", sort: (s) => s.hyperliquid?.buffer_before_protected_after },
          ]} />
          <div className="muted" style={{ fontSize: 11, marginTop: 8 }}>
            "At risk" means losses would exceed your equity above maintenance margin that is not protected spot, so the account would be leaning on that spot as collateral.
          </div>
        </Card>
        <Card title="Hypothetical daily P&L, current book" right="last 120 days">
          <SignedBars data={v.pnl_history || []} x="date" y="pnl" fmt={(x) => money(x)} />
        </Card>
      </div>
      <CustomStress />
      <div className="grid g3">
        <Card title="Exposures">
          <Table rows={[
            { k: "Gross", v: r.exposures.gross }, { k: "Net", v: r.exposures.net },
            { k: "β-adj net (SPX)", v: r.exposures.beta_adj_net_spx }, { k: "β-adj net (BTC)", v: r.exposures.beta_adj_net_btc },
            { k: "Long", v: r.exposures.long }, { k: "Short", v: r.exposures.short },
          ]} cols={[{ key: "k", label: "", left: true }, { key: "v", label: "$", render: (x) => <span className="num">{money(x.v)}</span> }]} />
        </Card>
        <Card title="Factor exposures" right="equities, $ per 1.0 factor move">
          <Table rows={r.factor_exposures} empty="Needs equity positions" cols={[
            { key: "factor", label: "", left: true },
            { key: "dollar_exposure", label: "$", render: (f) => <span className="num">{money(f.dollar_exposure)}</span> },
            { key: "bar", label: "", render: (f) => <DivBar v={f.dollar_exposure} max={maxFac} />, sort: (f) => f.dollar_exposure },
          ]} />
        </Card>
        <Card title="Liquidity" right="days to exit at ADV participation">
          <Table rows={r.liquidity} cols={[
            { key: "symbol", label: "", left: true },
            { key: "notional", label: "Notional", render: (x) => <span className="num">{money(x.notional)}</span> },
            { key: "days_to_exit", label: "Days", render: (x) => <span className={`num ${x.days_to_exit > 1 ? "neg" : ""}`}>{days(x.days_to_exit)}</span> },
          ]} />
        </Card>
      </div>
      <div className="grid g2">
        <Card title="Correlation (90d)" right="blue negative · red positive">
          {corr.symbols.length > 1 ? (
            <div className="scroll">
              <table className="heat">
                <thead><tr><th />{corr.symbols.map((s: string) => <th key={s} style={{ textAlign: "center" }}>{s}</th>)}</tr></thead>
                <tbody>
                  {corr.matrix.map((row: number[], i: number) => (
                    <tr key={i}><td className="l"><b>{corr.symbols[i]}</b></td>
                      {row.map((c, j) => <td key={j} className="num" style={{ background: i === j ? "var(--surface-2)" : heat(c) }}>{c.toFixed(2)}</td>)}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <div className="empty">Need 2+ positions</div>}
        </Card>
        <Card title="Stops">
          <Table rows={r.stops} empty="Set stops on the Portfolio tab" cols={[
            { key: "symbol", label: "", left: true, render: (s) => <b>{s.symbol}</b> },
            { key: "price", label: "Price", render: (s) => <span className="num">{num(s.price)}</span> },
            { key: "stop", label: "Stop", render: (s) => <span className="num">{num(s.stop)}</span> },
            { key: "dist_to_stop_pct", label: "Distance", render: (s) => <span className={`num ${s.breached ? "neg" : ""}`}>{s.breached ? "BREACHED" : `${num(s.dist_to_stop_pct, 1)}%`}</span> },
          ]} />
        </Card>
      </div>
    </div>
  );
}
