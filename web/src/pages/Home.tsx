import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { t, u } from "../lib/i18n";
import { useApp } from "../lib/state";

export default function Home() {
  const { country, lang, pack } = useApp();
  const nav = useNavigate();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const primary = pack?.helplines.find((h) => h.primary);

  async function start() {
    setBusy(true);
    setErr("");
    try {
      const c = await api.createCase(country, lang);
      nav(`/case/${c.id}`);
    } catch (e) {
      setErr(String((e as Error).message));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="stack">
      <h1>{t(lang, "tagline")}</h1>

      {country === "SG" && <p className="card alert">First: call your bank’s 24/7 anti-scam hotline or use its kill switch. Then call 1799 and lodge a police report.</p>}
      {primary && (
        <a className={`btn ${country === "SG" ? "ghost" : "call"}`} href={`tel:${primary.number}`}>
          📞 {t(lang, "callNow")} {primary.number}
        </a>
      )}
      <p className="muted small">
        {country === "SG" ? "Bank first, then ScamShield 1799 and the police report." : u(lang, "Call first, even before using this app. Then contact your bank’s fraud line.")}
      </p>
      <button onClick={start} disabled={busy}>
        {busy ? (lang === "hi" ? "रिपोर्ट खोली जा रही है…" : "Opening your report…") : `${t(lang, "imVictim")} →`}
      </button>
      {err && <p className="issue">{err}</p>}
      <div className="grid2">
        <Link className="btn ghost" to="/check">
          ⚠️ {t(lang, "precheck")}
        </Link>
        <Link className="btn ghost" to="/recovery">
          🛡️ {t(lang, "recovery")}
        </Link>
      </div>
      <div className="card">
        <h3>{u(lang, "Why the first hour matters")}</h3>
        <p className="small">
          {lang === "hi" ? "ठग पैसे को लगभग एक घंटे में कई खातों में घुमा देते हैं। सही ट्रांज़ैक्शन नंबर के साथ जल्दी दी गई शिकायत से बैंक और पुलिस को पैसा रोकने का सबसे अच्छा मौका मिलता है। पैसे वापस मिलने की गारंटी नहीं है।" : "Scammers move money through several accounts within about an hour. A fast report with the correct transaction reference gives banks and police the best chance to hold it. Recovery is not guaranteed."}
        </p>
        <ol className="small howto">
          <li>{lang === "hi" ? "हेल्पलाइन और बैंक को कॉल करें" : "Call the helpline and your bank"}</li>
          <li>{lang === "hi" ? "भुगतान के स्क्रीनशॉट डालें — Gemini विवरण पढ़ता है" : "Add payment screenshots — Gemini reads the details"}</li>
          <li>{lang === "hi" ? "हर जानकारी जाँचें और पुष्टि करें" : "Check and confirm every value"}</li>
          <li>{lang === "hi" ? "शिकायत, कॉल स्क्रिप्ट और बैंक पत्र कॉपी करें" : "Copy your complaint, call script and bank letter"}</li>
        </ol>
      </div>
      <p className="small muted">{lang === "hi" ? "आपकी रिपोर्ट सिर्फ़ इस ब्राउज़र टैब में निजी रहती है। टैब बंद करने से पहले दस्तावेज़ सहेज लें।" : "Your report stays private to this browser tab. Save your documents before closing it."}</p>
    </div>
  );
}
