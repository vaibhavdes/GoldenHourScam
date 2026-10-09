import { useState } from "react";
import { Link } from "react-router-dom";
import { SCAM_LABELS, Spinner } from "../components/ui";
import { api, type Precheck } from "../lib/api";
import { t, u } from "../lib/i18n";
import { useApp } from "../lib/state";

export default function Check({ mode }: { mode: "precheck" | "recovery" }) {
  const { country, lang } = useApp();
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<Precheck | null>(null);
  const [err, setErr] = useState("");

  async function run() {
    setBusy(true);
    setErr("");
    setRes(null);
    try {
      setRes(mode === "precheck" ? await api.precheck(text, country, lang) : await api.recoveryCheck(text, country, lang));
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="stack">
      <h1>{mode === "precheck" ? t(lang, "precheck") : t(lang, "recovery")}</h1>
      <p className="muted">
        {mode === "precheck"
          ? u(lang, "Describe the call or paste the message. Do not send any money while you check.")
          : u(lang, "Paste the message from the person offering to get your money back.")}
      </p>

      <label htmlFor="check-message">{lang === "hi" ? "मैसेज या कॉल की जानकारी" : "Message or call details"}</label>
      <textarea id="check-message"
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder={
          lang === "hi" ? "कॉल या मैसेज की जानकारी यहाँ लिखें…" : mode === "precheck"
            ? "Paste the message or describe what the caller asked you to do…"
            : "Describe the recovery offer and any payment or information requested…"
        }
      />
      <button onClick={run} disabled={busy || text.trim().length < 10}>
        {t(lang, "checkNow")}
      </button>
      {busy && <Spinner />}
      {err && <p className="issue">{err}</p>}
      {res && (
        <div className={`card ${res.verdict === "likely_scam" ? "alert" : ""}`}>
          <h2>
            {res.verdict === "likely_scam" ? u(lang, "🛑 STOP - this looks like a scam") : res.verdict === "suspicious" ? u(lang, "⚠️ Suspicious") : u(lang, "Not sure")}
          </h2>
          <p>
            <b>{res.advice}</b>
          </p>
          {res.scam_type !== "unknown" && <p className="pill red">{u(lang, SCAM_LABELS[res.scam_type])}</p>}
          <ul>
            {res.red_flags.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
          <p className="small">{u(lang, "Already sent money?")}<Link to="/">{u(lang, "Go to SOS →")}</Link>
          </p>
        </div>
      )}
    </div>
  );
}
