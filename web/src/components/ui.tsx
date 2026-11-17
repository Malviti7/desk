import { ReactNode, useMemo, useState } from "react";
import {
  CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis, Bar, BarChart, Cell,
} from "recharts";
import { chg, isNum, num, sign } from "../fmt";

export function Card({ title, right, children, className = "" }: { title?: ReactNode; right?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <div className={`card ${className}`}>
      {title && <h3>{title}{right && <span className="right">{right}</span>}</h3>}
      {children}
    </div>
  );
}

export function Tile({ label, value, sub, cls = "" }: { label: string; value: ReactNode; sub?: ReactNode; cls?: string }) {
  return (
    <div className="card tile">
      <div className="label">{label}</div>
      <div className={`value num ${cls}`}>{value}</div>
      {sub && <div className="sub">{sub}</div>}
    </div>
  );
}

export function Status({ status, label }: { status: string; label?: string }) {
  const text = label ?? { green: "OK", amber: "Watch", red: "Alert", na: "n/a" }[status] ?? status;
  return <span className={`status ${status}`}><span className="dot" />{text}</span>;
}

export function Chg({ v, unit = "%", d = 2 }: { v: any; unit?: string; d?: number }) {
  return <span className={`num ${sign(v)}`}>{chg(v, unit, d)}</span>;
}

/** Tiny inline trend line. Single series, no legend; hover shows nothing (the row has the numbers). */
export function Spark({ data, width = 90, height = 24 }: { data?: number[]; width?: number; height?: number }) {
  if (!data || data.length < 2) return <span className="muted">–</span>;
  const min = Math.min(...data), max = Math.max(...data);
  const span = max - min || 1;
  const pts = data.map((v, i) => `${(i / (data.length - 1)) * width},${height - 2 - ((v - min) / span) * (height - 4)}`).join(" ");
  const up = data[data.length - 1] >= data[0];
  return (
    <svg width={width} height={height} aria-hidden>
      <polyline points={pts} fill="none" stroke={up ? "var(--pos)" : "var(--neg)"} strokeWidth={1.5} strokeLinejoin="round" />
    </svg>
  );
}

export type Col<T> = { key: string; label: string; render?: (r: T) => ReactNode; sort?: (r: T) => any; left?: boolean };

export function Table<T extends Record<string, any>>({ rows, cols, empty = "No data yet", initialSort }: { rows: T[]; cols: Col<T>[]; empty?: string; initialSort?: string }) {
  const [sortKey, setSortKey] = useState<string | undefined>(initialSort);
  const [asc, setAsc] = useState(false);
  const sorted = useMemo(() => {
    if (!sortKey) return rows;
    const c = cols.find((x) => x.key === sortKey);
    const get = c?.sort ?? ((r: T) => r[sortKey]);
    return [...rows].sort((a, b) => {
      const x = get(a), y = get(b);
      if (x == null) return 1;
      if (y == null) return -1;
      return (x > y ? 1 : x < y ? -1 : 0) * (asc ? 1 : -1);
    });
  }, [rows, cols, sortKey, asc]);
  if (!rows?.length) return <div className="empty">{empty}</div>;
  return (
    <div className="scroll">
      <table>
        <thead>
          <tr>
            {cols.map((c) => (
              <th key={c.key} className={c.left ? "l" : ""} onClick={() => { setAsc(sortKey === c.key ? !asc : false); setSortKey(c.key); }}>
                {c.label}{sortKey === c.key ? (asc ? " ▲" : " ▼") : ""}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((r, i) => (
            <tr key={i}>
              {cols.map((c) => <td key={c.key} className={c.left ? "l" : ""}>{c.render ? c.render(r) : r[c.key]}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Standard indicator table: name, value, 1d/1w/1m, 1y percentile, spark. */
export function IndicatorTable({ rows }: { rows: any[] }) {
  return (
    <Table rows={rows || []} cols={[
      { key: "name", label: "", left: true },
      { key: "value", label: "Last", render: (r) => <span className="num">{num(r.value)}</span> },
      { key: "chg_1d", label: "1d", render: (r) => <Chg v={r.chg_1d} unit={r.chg_unit} /> },
      { key: "chg_1w", label: "1w", render: (r) => <Chg v={r.chg_1w} unit={r.chg_unit} /> },
      { key: "chg_1m", label: "1m", render: (r) => <Chg v={r.chg_1m} unit={r.chg_unit} /> },
      { key: "pctile_1y", label: "1y %ile", render: (r) => <span className="num secondary">{isNum(r.pctile_1y) ? r.pctile_1y.toFixed(0) : "–"}</span> },
      { key: "spark", label: "90d", render: (r) => <Spark data={r.spark} />, sort: () => 0 },
    ]} />
  );
}

const TT = ({ active, payload, label, fmt }: any) =>
  active && payload?.length ? (
    <div className="tt">
      <div className="muted">{label}</div>
      {payload.map((p: any) => (
        <div key={p.dataKey} className="num"><span style={{ color: p.color }}>■</span> {p.name}: {fmt ? fmt(p.value) : num(p.value)}</div>
      ))}
    </div>
  ) : null;

/** Line chart with crosshair tooltip. One y-axis only. Legend shown for 2+ series. */
export function LineViz({ data, x, series, height = 220, fmt, zero = false }: {
  data: any[]; x: string; series: { key: string; name: string; color?: string }[]; height?: number; fmt?: (v: number) => string; zero?: boolean;
}) {
  if (!data?.length) return <div className="empty">No data yet</div>;
  const colors = ["var(--series-1)", "var(--series-2)", "var(--series-3)"];
  return (
    <div>
      {series.length > 1 && (
        <div className="row" style={{ marginBottom: 6 }}>
          {series.map((s, i) => <span key={s.key} className="secondary" style={{ fontSize: 12 }}><span style={{ color: s.color ?? colors[i] }}>━</span> {s.name}</span>)}
        </div>
      )}
      <ResponsiveContainer width="100%" height={height}>
        <LineChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid stroke="var(--grid)" vertical={false} />
          <XAxis dataKey={x} tickLine={false} axisLine={{ stroke: "var(--border)" }} minTickGap={40} />
          <YAxis tickLine={false} axisLine={false} width={56} domain={["auto", "auto"]} tickFormatter={(v) => (fmt ? fmt(v) : num(v, 1))} />
          {zero && <ReferenceLine y={0} stroke="var(--text-muted)" />}
          <Tooltip content={<TT fmt={fmt} />} cursor={{ stroke: "var(--text-muted)", strokeDasharray: "3 3" }} />
          {series.map((s, i) => (
            <Line key={s.key} type="monotone" dataKey={s.key} name={s.name} stroke={s.color ?? colors[i]} strokeWidth={2} dot={false} activeDot={{ r: 4 }} isAnimationActive={false} />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

/** Bars colored by sign (gain/loss), with a zero baseline. */
export function SignedBars({ data, x, y, height = 200, fmt }: { data: any[]; x: string; y: string; height?: number; fmt?: (v: number) => string }) {
  if (!data?.length) return <div className="empty">No data yet</div>;
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 0 }} barCategoryGap={2}>
        <CartesianGrid stroke="var(--grid)" vertical={false} />
        <XAxis dataKey={x} tickLine={false} axisLine={{ stroke: "var(--border)" }} minTickGap={40} />
        <YAxis tickLine={false} axisLine={false} width={56} tickFormatter={(v) => (fmt ? fmt(v) : num(v, 0))} />
        <ReferenceLine y={0} stroke="var(--text-muted)" />
        <Tooltip content={<TT fmt={fmt} />} cursor={{ fill: "rgba(255,255,255,0.04)" }} />
        <Bar dataKey={y} name="P&L" radius={[4, 4, 0, 0]} isAnimationActive={false}>
          {data.map((d, i) => <Cell key={i} fill={d[y] >= 0 ? "var(--pos)" : "var(--neg)"} />)}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

/** Horizontal diverging bar inside a table cell. */
export function DivBar({ v, max }: { v: number; max: number }) {
  if (!isNum(v) || !max) return null;
  const w = Math.min(Math.abs(v) / max, 1) * 50;
  return (
    <div className="bar-track" style={{ width: 140 }} title={num(v)}>
      <div style={{ position: "absolute", left: "50%", top: -2, bottom: -2, width: 1, background: "var(--text-muted)" }} />
      <div className="bar-fill" style={{ left: v >= 0 ? "50%" : `${50 - w}%`, width: `${w}%`, background: v >= 0 ? "var(--pos)" : "var(--neg)" }} />
    </div>
  );
}

export function Loading({ error }: { error?: string | null }) {
  return error ? <div className="card err">Could not load: {error}</div> : <div className="empty">Loading…</div>;
}
