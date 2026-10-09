import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Link, NavLink, Route, Routes, useLocation } from "react-router-dom";
import "./styles.css";
import { AppProvider, useApp } from "./lib/state";
import { u, type Lang } from "./lib/i18n";
import Home from "./pages/Home";
import CaseFlow from "./pages/CaseFlow";
import Check from "./pages/Check";
import Shared from "./pages/Shared";
import Console from "./pages/Console";
import ConsoleCase from "./pages/ConsoleCase";
import Patterns from "./pages/Patterns";

function Header() {
  const { country, setCountry, lang, setLang, packs, bigText, setBigText } = useApp();
  const inCase = useLocation().pathname.startsWith("/case/");
  return (
    <header className="topbar">
      <Link to="/" className="brand" aria-label="GoldenHour home">
        <img src="/icon.svg" alt="" width={28} height={28} /> GoldenHour
      </Link>
      <nav className="topnav">
        {!inCase && <select aria-label="Country" value={country} onChange={(e) => setCountry(e.target.value)}>
          {(packs.length ? packs : [{ code: "IN", name: "India" }]).map((p) => (
            <option key={p.code} value={p.code}>
              {p.name}
            </option>
          ))}
        </select>}
        <select aria-label="Language" value={lang} onChange={(e) => setLang(e.target.value as Lang)}>
          <option value="en">English</option>
          <option value="hi">हिन्दी</option>
          <option value="ms">Bahasa Melayu (basic)</option>
        </select>
        <button className="ghost small" aria-pressed={bigText} onClick={() => setBigText(!bigText)} title="Large text">
          A+
        </button>
        <NavLink to="/console" className="small">
          Your reports
        </NavLink>
        <NavLink to="/patterns" className="small">Scam warning signs</NavLink>
      </nav>
    </header>
  );
}

function App() {
  const { lang } = useApp();
  const location = useLocation();
  return (
    <>
      <Header />
      <main className={location.pathname.startsWith("/console") ? "wide" : undefined}>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/case/:id" element={<CaseFlow />} />
          <Route path="/check" element={<Check mode="precheck" />} />
          <Route path="/recovery" element={<Check mode="recovery" />} />
          <Route path="/h/:token" element={<Shared />} />
          <Route path="/patterns" element={<Patterns />} />
          <Route path="/console" element={<Console />} />
          <Route path="/console/:id" element={<ConsoleCase />} />
          <Route path="*" element={<div className="card"><h1>Page not found</h1><Link to="/">Return to GoldenHour</Link></div>} />
        </Routes>
      </main>
      <footer className="foot">
        {u(lang, "GoldenHour prepares drafts only. It does not file complaints or contact anyone for you, and is not a government service or legal advice.")}
      </footer>
    </>
  );
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <AppProvider>
        <App />
      </AppProvider>
    </BrowserRouter>
  </React.StrictMode>,
);

if (import.meta.env.PROD && "serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    void navigator.serviceWorker.register("/sw.js").catch(() => {});
  });
}
