import { u } from "../lib/i18n";
import { useApp } from "../lib/state";
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { SCAM_LABELS } from "../components/ui";
import { api } from "../lib/api";

/** Helper mode: read-only, expiring view for a family member. */
export default function Shared() {
  const { lang } = useApp();
  const { token = "" } = useParams();
  const [d, setD] = useState<Record<string, any> | null>(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    api.shared(token).then(setD).catch((e) => setErr(e.message));
  }, [token]);
  if (err) return <p className="issue">{err}</p>;
  if (!d) return <p>{u(lang, "Loading…")}</p>;
  return (
    <div className="stack">
      <h1>{lang === "hi" ? "केस में सहायता" : "Helping with case"} {d.case_id}</h1>
      <p className="pill red">{u(lang, SCAM_LABELS[d.scam_type] ?? d.scam_type)}</p>
      {d.explanation && <p>{d.explanation}</p>}
      <div className="card">
        <h3>{u(lang, "Helplines")}</h3>
        {d.helplines.map((h: any) => (
          <p key={h.id}>
            <a href={`tel:${h.number}`}>{h.number}</a> - {h.label}
          </p>
        ))}
      </div>
      <div className="card">
        <h3>{u(lang, "Progress")}</h3>
        {d.steps.map((s: any) => (
          <p key={s.id}>
            {s.done ? "✅" : "⬜"} {s.label}
          </p>
        ))}
      </div>
      <div className="card">
        <h3>{u(lang, "Transfers")}</h3>
        {d.transactions.map((t: any, i: number) => (
          <p key={i}>
            {t.amount} · {t.time ? new Date(t.time).toLocaleString() : "-"} · {lang === "hi" ? "संदर्भ" : "ref"} {t.reference ?? "-"}
          </p>
        ))}
      </div>
      <p className="muted small">{u(lang, "This read-only link expires in 24 hours. Personal details are hidden.")}</p>
    </div>
  );
}
