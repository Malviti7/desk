import { useEffect, useMemo, useState } from "react";
import { useApi } from "../api";
import { ChartCfg, msLink, toTV, tvLink, TVChart } from "../components/TVChart";
import { num } from "../fmt";

type Pick = { symbol: string; crypto: boolean };

function fromHash(): Pick | null {
  const m = decodeURIComponent(location.hash.slice(1)).match(/^Charts\/([^~]+)(~c)?$/);
  return m ? { symbol: m[1], crypto: !!m[2] } : null;
}

const INTERVALS = [["5", "5m"], ["15", "15m"], ["60", "1h"], ["240", "4h"], ["D", "D"], ["W", "W"], ["M", "M"]];

export function RatingBadges({ r }: { r: any }) {
  if (!r) return null;
  const b = (label: string, v: any) => (v == null || v === "" ? null : <span className="pill" key={label}>{label} <b className="num">{typeof v === "number" ? v.toFixed(0) : v}</b></span>);
  return (
    <span>
      {b("Comp", r.composite)}{b("EPS", r.eps_rating)}{b("RS", r.rs)}{b("SMR", r.smr)}{b("A/D", r.acc_dis)}
      {r.pattern && <span className="pill">{r.pattern}</span>}
      {r.buy_point && <span className={`pill ${r.zone === "buy zone" ? "book" : ""}`}>BP {num(r.buy_point)} · {r.dist_to_buy_pct != null ? `${r.dist_to_buy_pct > 0 ? "+" : ""}${r.dist_to_buy_pct.toFixed(1)}%` : "–"}</span>}
    </span>
  );
}

export default function Charts() {
  const { data: cfg } = useApi<ChartCfg>("/charts/config", 600);
  const { data: leaders } = useApi<any[]>("/leaders", 300);
  const ratings = useMemo(() => Object.fromEntries((leaders || []).map((l) => [l.symbol, l])), [leaders]);
  const [layout, setLayout] = useState(1);
  const [interval, setInterval] = useState("D");
  const [active, setActive] = useState(0);
  const [panels, setPanels] = useState<Pick[]>(() => {
    const h = fromHash();
    return [h || { symbol: "SPY", crypto: false }, { symbol: "BTC", crypto: true }, { symbol: "QQQ", crypto: false }, { symbol: "ETH", crypto: true }];
  });
  const [custom, setCustom] = useState("");

  useEffect(() => {
    const onHash = () => { const h = fromHash(); if (h) setPanels((p) => p.map((x, i) => (i === active ? h : x))); };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, [active]);
  useEffect(() => { if (cfg?.default_interval) setInterval(cfg.default_interval); }, [cfg?.default_interval]);

  const pick = (p: Pick) => setPanels((ps) => ps.map((x, i) => (i === active ? p : x)));
  const height = layout === 1 ? "calc(100vh - 190px)" : "calc((100vh - 230px) / 2)";
  const shown = panels.slice(0, layout);

  return (
    <div className="page" style={{ gridTemplateColumns: "190px 1fr", alignItems: "start" }}>
      <div className="card" style={{ position: "sticky", top: 8, maxHeight: "calc(100vh - 140px)", overflowY: "auto" }}>
        <div className="row" style={{ marginBottom: 8 }}>
          <input placeholder="Any symbol" value={custom} onChange={(e) => setCustom(e.target.value.toUpperCase())} style={{ width: "100%" }}
            onKeyDown={(e) => { if (e.key === "Enter" && custom) { pick({ symbol: custom, crypto: false }); setCustom(""); } }} />
        </div>
        {Object.entries(cfg?.groups || {}).map(([g, items]) => items.length ? (
          <div key={g} style={{ marginBottom: 10 }}>
            <h3 style={{ margin: "6px 0" }}>{g}</h3>
            {items.map((it) => (
              <div key={g + it.symbol} className="sym-item" onClick={() => pick(it)}>
                <span>{it.symbol}</span>
                {ratings[it.symbol]?.rs != null && <span className="muted num">RS {ratings[it.symbol].rs.toFixed(0)}</span>}
              </div>
            ))}
          </div>
        ) : null)}
      </div>
      <div className="grid">
        <div className="row">
          <span className="muted">Layout</span>
          {[1, 2, 4].map((n) => <button key={n} className={`btn ${layout === n ? "primary" : ""}`} onClick={() => { setLayout(n); setActive(0); }}>{n}</button>)}
          <span className="muted" style={{ marginLeft: 12 }}>Interval</span>
          {INTERVALS.map(([v, l]) => <button key={v} className={`btn ${interval === v ? "primary" : ""}`} onClick={() => setInterval(v)}>{l}</button>)}
          {layout > 1 && <span className="muted" style={{ marginLeft: 12 }}>Click a panel, then a symbol to load it there</span>}
        </div>
        <div className="grid" style={{ gridTemplateColumns: layout === 1 ? "1fr" : "1fr 1fr" }}>
          {shown.map((p, i) => {
            const tv = toTV(p.symbol, p.crypto, cfg);
            return (
              <div key={i} className="card" onClick={() => setActive(i)}
                style={{ padding: 8, outline: layout > 1 && i === active ? "1px solid var(--accent)" : "none" }}>
                <div className="row" style={{ marginBottom: 6, justifyContent: "space-between" }}>
                  <span className="row"><b style={{ fontSize: 15 }}>{p.symbol}</b><span className="muted">{tv}</span><RatingBadges r={ratings[p.symbol]} /></span>
                  <span className="row">
                    <a className="btn" href={tvLink(p.symbol, p.crypto, cfg)} target="_blank" rel="noreferrer">TradingView ↗</a>
                    {!p.crypto && <a className="btn" href={msLink(p.symbol, cfg)} target="_blank" rel="noreferrer">MarketSurge ↗</a>}
                  </span>
                </div>
                <TVChart tvSymbol={tv} interval={interval} height={height} studies={cfg?.studies || []} />
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
