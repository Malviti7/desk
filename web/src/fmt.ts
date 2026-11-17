export const isNum = (x: any): x is number => typeof x === "number" && Number.isFinite(x);

export function money(x: any, compact = true): string {
  if (!isNum(x)) return "–";
  const s = x < 0 ? "-" : "";
  const a = Math.abs(x);
  if (compact && a >= 1e9) return `${s}$${(a / 1e9).toFixed(2)}B`;
  if (compact && a >= 1e6) return `${s}$${(a / 1e6).toFixed(2)}M`;
  if (compact && a >= 1e4) return `${s}$${(a / 1e3).toFixed(1)}K`;
  return `${s}$${a.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

export function num(x: any, d = 2): string {
  if (!isNum(x)) return "–";
  const a = Math.abs(x);
  if (a >= 1e9) return `${(x / 1e9).toFixed(2)}B`;
  if (a >= 1e6) return `${(x / 1e6).toFixed(2)}M`;
  if (a >= 1e4) return x.toLocaleString(undefined, { maximumFractionDigits: 0 });
  if (a > 0 && a < 1) return x.toPrecision(4);
  return x.toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });
}

export function fixed(x: any, d = 2): string {
  if (!isNum(x)) return "–";
  return x.toFixed(d);
}

export function days(x: any): string {
  if (!isNum(x)) return "–";
  return x < 0.01 ? "<0.01" : x.toFixed(2);
}

export function chg(x: any, unit = "%", d = 2): string {
  if (!isNum(x)) return "–";
  const v = unit === "bp" ? x.toFixed(0) : x.toFixed(d);
  return `${x > 0 ? "+" : ""}${v}${unit}`;
}

export const sign = (x: any) => (!isNum(x) || x === 0 ? "" : x > 0 ? "pos" : "neg");
