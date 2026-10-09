import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { CopyButton, GoldenTimer, SCAM_LABELS, Spinner } from "../components/ui";
import { api, type Case, type HoldRequest, type ScoreCard } from "../lib/api";
import { fmtMoney } from "../lib/state";

type Data = {
  case: Case;
  score: ScoreCard;
  linked_cases: { case_id: string; shared: string[]; total_lost: number }[];
};

const FACTOR_LABEL: Record<string, string> = {
  time_since_transfer: "Time since transfer",
  payment_rail: "Payment rail",
  report_completeness: "Report completeness",
  beneficiary_linked_cases: "Beneficiary in other cases",
};

export default function ConsoleCase() {
  const { id = "" } = useParams();
  const [d, setD] = useState<Data | null>(null);
  const [hr, setHr] = useState<HoldRequest | null>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    let active = true;
    setD(null); setHr(null); setErr("");
    api.consoleCase(id).then(data => { if (active) setD(data); }).catch((e) => { if (active) setErr(e.message); });
    return () => { active = false; };
  }, [id]);

  if (err && !d) return <p role="alert" className="issue">{err}</p>;
  if (!d) return <Spinner text="Loading case…" />;
  const c = d.case;
  const first = c.transactions.filter(t => t.direction === "debit" && t.timestamp.valid).map((t) => t.timestamp.value).filter(Boolean).sort((a, b) => Date.parse(a!) - Date.parse(b!))[0];
  const outgoing = c.transactions.filter(t => t.direction === "debit");
  const canHold = outgoing.length > 0 && outgoing.every(t => t.confirmed && t.utr.valid && t.amount.valid && (t.beneficiary.vpa.valid || t.beneficiary.account.valid) && ["UPI", "IMPS", "NEFT", "RTGS", "DUITNOW", "PAYNOW", "BANK_TRANSFER"].includes(t.rail));

  return (
    <div className="wide stack" style={{ margin: "0 auto" }}>
      <Link to="/console" className="small">
        ← Your reports
      </Link>
      {err && <p role="alert" className="issue">{err}</p>}
      <div className="row" style={{ justifyContent: "space-between" }}>
        <div>
          <h1>
            {c.id} <span className="pill red">{SCAM_LABELS[c.scam_type]}</span>
          </h1>
          <div className="muted small">
            {c.country} · {c.transactions.length} transfer(s)
          </div>
        </div>
        <GoldenTimer since={first} label="since first transfer" />
      </div>
      <Link className="btn ghost" to={`/case/${c.id}?step=review`}>Review case and prepare report</Link>

      <div className="grid2">
        <div className="card">
          <h2>Response priority {d.score.score.toFixed(0)}/100</h2>
          <details><summary>How priority is calculated</summary><p className="small"><code>priority = min(100, 100 × time × rail × (0.4 + 0.6 × completeness) + link bonus)</code></p></details>
          <p className="muted small">Heuristic policy, tunable by the bank; not a recovery probability. Link bonus = 2 × min(linked cases, 5).</p>
          <table>
            <tbody>
              {d.score.factors.map((f) => (
                <tr key={f.name}>
                  <td>{FACTOR_LABEL[f.name] ?? f.name}</td>
                  <td>
                    <b>{f.value}</b>
                  </td>
                  <td className="muted small">{f.name === "beneficiary_linked_cases" ? `+${Math.min(Number(f.value), 5) * 2}` : `×${f.weight}`}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {d.score.explanation && <p className="small">💡 {d.score.explanation}</p>}
          <p className="muted small">Deterministic score; AI only explains the listed factors.</p>
        </div>
        <div className="card">
          <h2>Linked cases ({d.linked_cases.length})</h2>
          {d.linked_cases.length === 0 && <p className="muted">No shared identifiers yet.</p>}
          {d.linked_cases.map((l) => (
            <p key={l.case_id} className="small">
              <Link to={`/console/${l.case_id}`}>{l.case_id}</Link> · {fmtMoney(l.total_lost, c.country === "MY" ? "MYR" : c.country === "SG" ? "SGD" : "INR")} · via{" "}
              <code>{l.shared.join(", ")}</code>
            </p>
          ))}
        </div>
      </div>

      <div className="card tablewrap">
        <h2>Transfers</h2>
        <table>
          <thead>
            <tr>
              <th>Time</th>
              <th>Rail</th>
              <th>Reference</th>
              <th>Amount</th>
              <th>Direction</th>
              <th>Beneficiary</th>
            </tr>
          </thead>
          <tbody>
            {c.transactions.map((t) => (
              <tr key={t.id}>
                <td>{t.timestamp.value ? new Date(t.timestamp.value).toLocaleString() : "-"}</td>
                <td>{t.rail}</td>
                <td>
                  <code>{t.utr.value ?? "-"}</code> {!t.utr.valid && <span className="pill red">check</span>}
                </td>
                <td>{t.amount.valid ? fmtMoney(Number(t.amount.value), t.currency) : "Check amount"}</td>
                <td>{t.direction === "credit" ? "Incoming · excluded from loss" : "Outgoing"}</td>
                <td className="small">
                  {[t.beneficiary.vpa.value, t.beneficiary.account.value, t.beneficiary.ifsc.value, t.beneficiary.bank.value]
                    .filter(Boolean)
                    .join(" · ")}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card">
          <h2>Hold request draft</h2>
        <p className="small muted">
          Hold requests cover only the disputed amounts. Review and confirm the transaction details first.
        </p>
        {!canHold && <p className="issue">Review missing or unconfirmed outgoing payment details before preparing a hold draft.</p>}
        <button disabled={!canHold} onClick={() => { setErr(""); api.holdRequest(c.id, {}).then(setHr).catch((e) => setErr(e.message)); }}>
          Prepare hold request draft
        </button>
        {hr && (
          <>
            <p>
              <span className={`pill ${hr.action === "HOLD_DISPUTED_AMOUNT" ? "green" : "amber"}`}>{hr.action}</span>
            </p>
            <pre className="letter">{hr.text}</pre>
            <CopyButton text={hr.text} />
          </>
        )}
      </div>
    </div>
  );
}
