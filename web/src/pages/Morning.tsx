import { useApi } from "../api";
import { Card, Chg, Loading, Status, Table, Tile } from "../components/ui";
import { money, num, sign } from "../fmt";

export function RegimeCard({ regime }: { regime: any }) {
  return (
    <Card title="Regime check" right={<span className="muted">{regime.reds} red · {regime.ambers} amber</span>}>
      <div className={`regime-label ${regime.label}`}>{regime.label}</div>
      <div style={{ marginTop: 8 }}>
        {regime.signals.map((s: any) => (
          <div className="signal" key={s.name}>
            <Status status={s.status} label={s.name} />
            <span className="num">{s.value}</span>
            <span className="why">{s.why}</span>
          </div>
        ))}
        {!regime.signals.length && <div className="empty">No data yet. Check the Data tab.</div>}
      </div>
    </Card>
  );
}

export function AlertList({ alerts }: { alerts: any[] }) {
  if (!alerts?.length) return <div className="empty">No alerts in the last 24h</div>;
  return (
    <div>
      {alerts.map((a, i) => (
        <div className="alert" key={i}>
          <span className={`sev ${a.severity}`}>{a.severity}</span>
          <span>{a.message}<div className="muted" style={{ fontSize: 11 }}>{a.category} · {a.ts?.slice(0, 16).replace("T", " ")} UTC</div></span>
        </div>
      ))}
    </div>
  );
}

export function NewsList({ items }: { items: any[] }) {
  if (!items?.length) return <div className="empty">No headlines</div>;
  return (
    <div>
      {items.map((n, i) => (
        <div className="news-item" key={i}>
          <a href={n.url} target="_blank" rel="noreferrer">{n.title}</a>
          <div className="src">
            {n.source} · {n.ts?.slice(5, 16).replace("T", " ")}{" "}
            {(n.tags || "").split(",").filter(Boolean).map((t: string) => <span key={t} className={`pill ${t.startsWith("$") ? "book" : ""}`}>{t}</span>)}
          </div>
        </div>
      ))}
    </div>
  );
}

export function CalendarList({ items }: { items: any[] }) {
  return (
    <Table rows={items || []} empty="Nothing scheduled" cols={[
      { key: "date", label: "Date", left: true, render: (r) => <span className="num">{r.date}</span> },
      { key: "kind", label: "Type", left: true, render: (r) => <span className="pill">{r.kind}</span> },
      { key: "name", label: "Event", left: true },
      { key: "detail", label: "", left: true, render: (r) => <span className="secondary">{r.detail}</span> },
    ]} />
  );
}

export default function Morning() {
  const { data: b, error } = useApi("/brief", 120);
  if (!b) return <Loading error={error} />;
  const bk = b.book || {};
  const ex = bk.exposures || {};
  const hl = bk.hyperliquid;
  const ws = b.risk?.worst_stress || {};
  return (
    <div className="page">
      <div className="grid g4">
        <Tile label="1d P&L" value={money(bk.pnl_1d)} cls={sign(bk.pnl_1d)} sub={`Unrealized ${money(bk.unrealized)}`} />
        <Tile label="Gross / Net" value={`${money(ex.gross)} / ${money(ex.net)}`} sub={`β-adj: SPX ${money(ex.beta_adj_net_spx)} · BTC ${money(ex.beta_adj_net_btc)}`} />
        <Tile label="1-day VaR 95%" value={money(b.risk?.var_95)} sub={ws.name ? `Worst stress: ${ws.name} ${money(ws.total_pnl)}` : "Add positions to see risk"} />
        {hl ? (
          <Tile label="Buffer before protected spot" value={money(hl.buffer_before_protected)} cls={hl.buffer_before_protected < 0 ? "neg" : ""}
            sub={`Headroom ${num(hl.headroom_pct, 0)}% · protected ${hl.protected?.join(", ")} ${money(hl.protected_spot_value)}`} />
        ) : <Tile label="Hyperliquid" value="–" sub="Set HYPERLIQUID_ADDRESS" />}
      </div>
      <div className="grid g2">
        <RegimeCard regime={b.regime} />
        <div className="grid">
          <Card title="Alerts" right="last 24h"><AlertList alerts={b.alerts} /></Card>
          <Card title="Biggest movers in the book">
            <Table rows={bk.biggest_movers || []} empty="No positions" cols={[
              { key: "symbol", label: "", left: true, render: (r) => <b>{r.symbol}</b> },
              { key: "account", label: "Acct", left: true, render: (r) => <span className="muted">{r.account}</span> },
              { key: "pnl_1d", label: "1d P&L", render: (r) => <span className={`num ${sign(r.pnl_1d)}`}>{money(r.pnl_1d)}</span> },
              { key: "notional", label: "Notional", render: (r) => <span className="num">{money(r.notional)}</span> },
              { key: "dist_to_stop_pct", label: "To stop", render: (r) => <span className="num">{r.dist_to_stop_pct == null ? "–" : `${r.dist_to_stop_pct.toFixed(1)}%`}</span> },
            ]} />
          </Card>
        </div>
      </div>
      <div className="grid g2">
        <Card title="Overnight">
          <Table rows={b.overnight || []} cols={[
            { key: "name", label: "", left: true },
            { key: "value", label: "Last", render: (r) => <span className="num">{num(r.value)}</span> },
            { key: "chg_1d", label: "1d", render: (r) => <Chg v={r.chg_1d} unit={r.chg_unit} /> },
            { key: "chg_1w", label: "1w", render: (r) => <Chg v={r.chg_1w} unit={r.chg_unit} /> },
          ]} />
        </Card>
        <div className="grid">
          <Card title="Next 7 days"><CalendarList items={b.calendar} /></Card>
          <Card title="Crypto crowding">
            <div className="secondary" style={{ marginBottom: 6 }}>OI-weighted funding <span className="num">{num(b.crypto?.oi_weighted_funding_ann, 1)}%</span> annualized</div>
            <Table rows={b.crypto?.crowded || []} empty="Nothing crowded" cols={[
              { key: "coin", label: "", left: true, render: (r) => <b>{r.coin}{r.held ? " •" : ""}</b> },
              { key: "funding_ann", label: "Funding (ann)", render: (r) => <span className="num">{num(r.funding_ann, 0)}%</span> },
              { key: "oi_usd", label: "OI", render: (r) => <span className="num">{money(r.oi_usd)}</span> },
              { key: "crowding", label: "", render: (r) => <span className="pill hot">{r.crowding}</span> },
            ]} />
          </Card>
        </div>
      </div>
      <div className="grid g2">
        <Card title="News on your book"><NewsList items={b.news_on_book} /></Card>
        <Card title="Macro & market headlines"><NewsList items={b.news_macro} /></Card>
      </div>
    </div>
  );
}
