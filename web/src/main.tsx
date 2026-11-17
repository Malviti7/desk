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

const TABS: Record<string, () => JSX.Element> = {
  Morning, Macro, Crypto, Equities, Portfolio, Risk, "News & Calendar": News, Ideas, Data,
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
  const initial = decodeURIComponent(location.hash.slice(1)) || "Morning";
  const [tab, setTab] = useState(TABS[initial] ? initial : "Morning");
  const { data: health } = useApi("/health", 60);
  useEffect(() => { location.hash = tab; }, [tab]);
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
