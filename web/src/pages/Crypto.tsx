import { useState } from "react";
import { useApi } from "../api";
import { Card, Chg, IndicatorTable, LineViz, Loading, Table, Tile } from "../components/ui";
import { openChart } from "../components/TVChart";
import { fixed, money, num, sign } from "../fmt";

function XvHistory({ coin }: { coin: string }) {
  const { data: oi } = useApi<any>(`/series/${encodeURIComponent(`cz:${coin}:oi_usd`)}?days=180`, 900);
  const { data: fu } = useApi<any>(`/series/${encodeURIComponent(`cz:${coin}:funding_ann`)}?days=180`, 900);
  const { data: ll } = useApi<any>(`/series/${encodeURIComponent(`cz:${coin}:liq_long`)}?days=90`, 900);
  const { data: ls } = useApi<any>(`/series/${encodeURIComponent(`cz:${coin}:liq_short`)}?days=90`, 900);
  const liq = (ll?.points || []).map((p: any, i: number) => ({ date: p.date, long: p.value, short: ls?.points?.[i]?.value }));
  return (
    <div className="grid g3">
      <Card title={`${coin} OI, all venues`} right="180d"><LineViz data={oi?.points || []} x="date" series={[{ key: "value", name: "OI" }]} fmt={(v) => money(v)} height={200} /></Card>
      <Card title={`${coin} OI-weighted funding, ann %`} right="180d"><LineViz data={fu?.points || []} x="date" series={[{ key: "value", name: "Funding" }]} zero fmt={(v) => `${v.toFixed(0)}%`} height={200} /></Card>
      <Card title={`${coin} liquidations`} right="90d"><LineViz data={liq} x="date" series={[{ key: "long", name: "Longs" }, { key: "short", name: "Shorts" }]} fmt={(v) => money(v)} height={200} /></Card>
    </div>
  );
}

function CrossVenue({ rows, onPick }: { rows: any[]; onPick: (c: string) => void }) {
  const [open, setOpen] = useState<string | null>(null);
  if (!rows?.length) return <div className="empty">Add COINALYZE_API_KEY to .env to see funding, OI and liquidations across exchanges</div>;
  return (
    <div>
      <Table rows={rows} initialSort="oi_usd" cols={[
        { key: "coin", label: "", left: true, render: (r) => <a style={{ cursor: "pointer" }} onClick={() => { setOpen(open === r.coin ? null : r.coin); onPick(r.coin); }}><b>{r.coin}</b> {open === r.coin ? "▾" : "▸"}</a> },
        { key: "oi_usd", label: "OI (all venues)", render: (r) => <span className="num">{money(r.oi_usd)}</span> },
        { key: "oi_chg_24h", label: "OI 24h", render: (r) => <Chg v={r.oi_chg_24h} /> },
        { key: "funding_ann_oiw", label: "Funding (OI-wtd, ann)", render: (r) => <span className={`num ${sign(r.funding_ann_oiw)}`}>{num(r.funding_ann_oiw, 1)}%</span> },
        { key: "funding_dispersion", label: "Venue spread", render: (r) => <span className="num">{r.funding_dispersion == null ? "–" : `${r.funding_dispersion.toFixed(1)}pts`}</span> },
        { key: "liq_long_24h", label: "Long liqs 24h", render: (r) => <span className="num">{money(r.liq_long_24h)}</span> },
        { key: "liq_short_24h", label: "Short liqs 24h", render: (r) => <span className="num">{money(r.liq_short_24h)}</span> },
        { key: "hyperliquid_share", label: "HL share", render: (r) => <span className="num">{r.hyperliquid_share == null ? "–" : `${r.hyperliquid_share.toFixed(0)}%`}</span> },
        { key: "flags", label: "", render: (r) => <>{r.crowding && <span className="pill hot">{r.crowding}</span>}{r.liq_skew && <span className="pill">{r.liq_skew}</span>}</>, sort: () => 0 },
      ]} />
      {open && (() => {
        const r = rows.find((x) => x.coin === open);
        return r ? (
          <div style={{ marginTop: 10 }}>
            <h3>{open} by venue</h3>
            <Table rows={r.venues} cols={[
              { key: "exchange", label: "", left: true },
              { key: "oi_usd", label: "OI", render: (v) => <span className="num">{money(v.oi_usd)}</span> },
              { key: "oi_share", label: "Share", render: (v) => <span className="num">{num(v.oi_share, 1)}%</span> },
              { key: "funding_ann", label: "Funding (ann)", render: (v) => <span className={`num ${sign(v.funding_ann)}`}>{num(v.funding_ann, 1)}%</span> },
              { key: "liq_long_24h", label: "Long liqs", render: (v) => <span className="num">{money(v.liq_long_24h)}</span> },
              { key: "liq_short_24h", label: "Short liqs", render: (v) => <span className="num">{money(v.liq_short_24h)}</span> },
            ]} />
          </div>
        ) : null;
      })()}
    </div>
  );
}

export default function Crypto() {
  const { data: c, error } = useApi("/crypto", 60);
  const [coin, setCoin] = useState("BTC");
  const { data: fh } = useApi<any[]>(`/crypto/funding/${coin}?days=14`, 300);
  if (!c) return <Loading error={error} />;
  const dvol = (c.implied_vol || [])[0];
  const xv = (c.cross_venue || []).find((x: any) => x.coin === coin);
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
      <Card title="Cross-venue derivatives" right={c.cross_venue?.length ? `Coinalyze · as of ${c.cross_venue[0].as_of?.slice(5, 16)} UTC · click a coin for venues` : "Coinalyze"}>
        <CrossVenue rows={c.cross_venue} onPick={setCoin} />
      </Card>
      <Card title="Hyperliquid perps" right="click a row to chart funding · • = held">
        <Table rows={c.perps} initialSort="oi_usd" cols={[
          { key: "coin", label: "", left: true, render: (r) => <a onClick={() => setCoin(r.coin)} style={{ cursor: "pointer" }}><b>{r.coin}</b>{r.held ? " •" : ""}</a> },
          { key: "chart", label: "", render: (r) => <a className="btn" title="Chart" onClick={() => openChart(r.coin, true)}>⤢</a>, sort: () => 0 },
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
      {xv && <XvHistory coin={coin} />}
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
