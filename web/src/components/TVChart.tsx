import { useEffect, useRef } from "react";

export type ChartCfg = {
  crypto_template: string;
  overrides: Record<string, string>;
  default_interval: string;
  studies: string[];
  marketsurge_url: string;
  tradingview_url: string;
  groups: Record<string, { symbol: string; crypto: boolean }[]>;
};

/** Map a Desk symbol to a TradingView symbol. */
export function toTV(symbol: string, crypto: boolean, cfg?: ChartCfg | null): string {
  if (cfg?.overrides?.[symbol]) return cfg.overrides[symbol];
  if (symbol.includes(":")) return symbol;
  if (crypto) return (cfg?.crypto_template || "BINANCE:{coin}USDT").replace("{coin}", symbol);
  return symbol;
}

export function tvLink(symbol: string, crypto: boolean, cfg?: ChartCfg | null) {
  const tv = toTV(symbol, crypto, cfg);
  return (cfg?.tradingview_url || "https://www.tradingview.com/chart/?symbol={tv_symbol}").replace("{tv_symbol}", encodeURIComponent(tv));
}

export function msLink(symbol: string, cfg?: ChartCfg | null) {
  return (cfg?.marketsurge_url || "https://marketsurge.investors.com/").replace("{symbol}", encodeURIComponent(symbol));
}

/** Navigate to the Charts tab with a symbol loaded. */
export function openChart(symbol: string, crypto = false) {
  location.hash = `Charts/${encodeURIComponent(symbol)}${crypto ? "~c" : ""}`;
}

/**
 * TradingView Advanced Chart widget (free embed, live data from TradingView).
 * It runs anonymously: your saved layouts and private scripts live in TradingView itself,
 * which the "TradingView ↗" button opens.
 */
export function TVChart({ tvSymbol, interval = "D", height = 520, studies = [] }: { tvSymbol: string; interval?: string; height?: number | string; studies?: string[] }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const host = ref.current;
    if (!host) return;
    host.innerHTML = "";
    const widget = document.createElement("div");
    widget.className = "tradingview-widget-container__widget";
    widget.style.height = "100%";
    widget.style.width = "100%";
    host.appendChild(widget);
    const s = document.createElement("script");
    s.src = "https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js";
    s.type = "text/javascript";
    s.async = true;
    s.innerHTML = JSON.stringify({
      autosize: true,
      symbol: tvSymbol,
      interval,
      timezone: "America/New_York",
      theme: "dark",
      style: "1",
      locale: "en",
      backgroundColor: "#1a1a19",
      gridColor: "rgba(46, 46, 43, 0.6)",
      allow_symbol_change: true,
      withdateranges: true,
      hide_side_toolbar: false,
      details: false,
      calendar: false,
      studies,
      support_host: "https://www.tradingview.com",
    });
    host.appendChild(s);
    return () => { host.innerHTML = ""; };
  }, [tvSymbol, interval, studies.join(",")]);
  return (
    <div className="tradingview-widget-container tv-frame" ref={ref} style={{ height, width: "100%" }}>
      <div className="empty">Loading TradingView chart for {tvSymbol}…</div>
    </div>
  );
}
