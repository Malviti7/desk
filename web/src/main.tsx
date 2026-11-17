import { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";
import { useApi } from "./api";
import Crypto from "./pages/Crypto";
import Equities from "./pages/Equities";
import Macro from "./pages/Macro";
import Morning from "./pages/Morning";
import { Data, Ideas, News } from "./pages/Other";
import Portfolio from "./pages/Portfolio";
import Risk from "./pages/Risk";
import Charts from "./pages/Charts";
import Leaders from "./pages/Leaders";

const TABS: Record<string, () => JSX.Element> = {
  Morning, Charts, Macro, Crypto, Equities, Leaders, Portfolio, Risk, "News & Calendar": News, Ideas, Data,
};

function Clock() {
  const [t, setT] = useState(new Date());
  useEffect(() => { const id = setInterval(() => setT(new Date()), 1000); return () => clearInterval(id); }, []);
  const ny = t.toLocaleTimeString("en-US", { timeZone: "America/New_York", hour12: false });
  const ldn = t.toLocaleTimeString("en-GB", { timeZone: "Europe/London", hour12: false, hour: "2-digit", minute: "2-digit" });
  const tky = t.toLocaleTimeString("en-GB", { timeZone: "Asia/Tokyo", hour12: false, hour: "2-digit", minute: "2-digit" });
  return <span className="meta num">NY {ny} · LDN {ldn} · TKY {tky}</span>;
}

function App() {
  const tabFromHash = () => {
    const t = decodeURIComponent(location.hash.slice(1)).split("/")[0];
    return TABS[t] ? t : "Morning";
  };
  const [tab, setTab] = useState(tabFromHash);
  const { data: health } = useApi("/health", 60);
  useEffect(() => {
    const on = () => setTab(tabFromHash());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  useEffect(() => { if (tabFromHash() !== tab) location.hash = tab; }, [tab]);
  const Page = TABS[tab];
  return (
    <div className="app">
      <div className="topbar">
        <span className="brand">DESK</span>
        {health?.demo && <span className="demo-badge">DEMO DATA</span>}
        <span className="spacer" />
        <Clock />
      </div>
      <nav className="tabs">
        {Object.keys(TABS).map((t) => <button key={t} className={`tab ${t === tab ? "active" : ""}`} onClick={() => setTab(t)}>{t}</button>)}
      </nav>
      <Page key={tab} />
    </div>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
