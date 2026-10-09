import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { SCAM_LABELS, Spinner } from "../components/ui";
import { api, type QueueRow } from "../lib/api";
import { fmtMoney } from "../lib/state";

function since(min: number | null): string {
  if (min == null) return "-";
  if (min < 60) return `${Math.round(min)} min`;
  if (min < 1440) return `${(min / 60).toFixed(1)} h`;
  return `${(min / 1440).toFixed(1)} d`;
}

type Cluster = { case_ids: string[]; shared_identifiers: string[]; victims: number; total_lost: number; currency: string };

export default function Console() {
  const nav = useNavigate();
  const [rows, setRows] = useState<QueueRow[] | null>(null);
  const [clusters, setClusters] = useState<Cluster[]>([]);
  const [country, setCountry] = useState("");
  const [view, setView] = useState<"queue" | "clusters">("queue");
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    setRows(null); setError("");
    const load = () => api.queue(country || undefined).then((data) => { if (active) { setRows(data); setError(""); } }).catch((e) => { if (active) setError(e.message); });
    load();
    const id = setInterval(load, 30000); // re-rank as the clock moves
    return () => { active = false; clearInterval(id); };
  }, [country]);
  useEffect(() => {
    if (view === "clusters") api.clusters().then(setClusters).catch((e) => setError(e.message));
  }, [view]);

  const recoverable = rows?.filter((r) => (r.minutes_since_txn ?? 1e9) <= 60).length ?? 0;
  const visibleClusters = clusters.filter(c => !country || c.currency === ({ IN: "INR", MY: "MYR", SG: "SGD" } as Record<string, string>)[country]);

  return (
    <div className="wide" style={{ margin: "0 auto" }}>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <div>
          <h1>Your reports</h1>
          <p className="muted small">Ranked by response priority, a heuristic rather than a recovery probability. Only reports created in this browser tab appear here.</p>
        </div>
        <div className="row">
          <select value={country} onChange={(e) => setCountry(e.target.value)} aria-label="Filter country">
            <option value="">All countries</option>
            <option value="IN">India</option>
            <option value="MY">Malaysia</option>
            <option value="SG">Singapore</option>
          </select>
          <button className={view === "queue" ? "small" : "ghost small"} onClick={() => setView("queue")}>
            Reports
          </button>
          <button className={view === "clusters" ? "small" : "ghost small"} onClick={() => setView("clusters")}>
            Linked accounts
          </button>
        </div>
      </div>

      {error && <p role="alert" className="issue">{error}</p>}

      {rows && (
        <div className="stats-grid">
          <div className="card">
            <div className="muted small">Saved reports</div>
            <div className="timer" style={{ color: "var(--ink)" }}>{rows.length}</div>
          </div>
          <div className="card">
            <div className="muted small">Inside golden hour</div>
            <div className="timer">{recoverable}</div>
          </div>
          <div className="card">
            <div className="muted small">Linked to other cases</div>
            <div className="timer" style={{ color: "var(--ink)" }}>{rows.filter((r) => r.linked > 0).length}</div>
          </div>
        </div>
      )}

      {view === "queue" &&
        (!rows ? (
          error ? <button className="ghost" onClick={() => window.location.reload()}>Retry loading</button> : <Spinner text="Loading queue…" />
        ) : (
          <div className="card tablewrap">
            <table>
              <thead>
                <tr>
                  <th>#</th>
                  <th>Score</th>
                  <th>Since transfer</th>
                  <th>Case</th>
                  <th>Type</th>
                  <th>Loss</th>
                  <th>Linked</th>
                </tr>
              </thead>
              <tbody>
                {rows.length === 0 && <tr><td colSpan={7}>No reports yet. <a href="/">Start a report</a> to review your payment details and prepare the documents.</td></tr>}
                {rows.map((r, i) => (
                  <tr key={r.case_id} className="click" onClick={() => nav(`/case/${r.case_id}${r.transactions ? "?step=review" : ""}`)}>
                    <td>{i + 1}</td>
                    <td>
                      {r.transactions ? <>
                        <b>{r.score.toFixed(0)}</b>
                        <div className="bar">
                          <span style={{ width: `${r.score}%` }} />
                        </div>
                      </> : <span className="muted small">Add transfers</span>}
                    </td>
                    <td>
                      <span className={`pill ${(r.minutes_since_txn ?? 1e9) <= 60 ? "red" : ""}`}>{since(r.minutes_since_txn)}</span>
                    </td>
                    <td>
                      <a href={`/case/${r.case_id}${r.transactions ? "?step=review" : ""}`} onClick={e => e.stopPropagation()}>{r.case_id}</a> <a className="small" href={`/console/${r.case_id}`} onClick={e => e.stopPropagation()}>Details</a> <span className="muted small">{r.country}</span>
                    </td>
                    <td>{r.transactions ? (SCAM_LABELS[r.scam_type] ?? r.scam_type) : <span className="muted small">In progress</span>}</td>
                    <td>{r.transactions ? fmtMoney(r.total_lost, r.currency) : "-"}</td>
                    <td>{r.linked > 0 ? <span className="pill amber">+{r.linked}</span> : "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}

      {view === "clusters" && (
        <div className="grid2">
          <div className="card tablewrap">
            <table>
              <thead>
                <tr>
                  <th>Cases</th>
                  <th>Total</th>
                  <th>Shared identifier</th>
                </tr>
              </thead>
              <tbody>
                {visibleClusters.length === 0 && <tr><td colSpan={3}>No linked accounts for this country yet.</td></tr>}
                {visibleClusters.map((c) => (
                  <tr key={c.case_ids.join()} className="click" onClick={() => nav(`/console/${c.case_ids[0]}`)}>
                    <td>
                      <b>{c.victims}</b>
                    </td>
                    <td>{fmtMoney(c.total_lost, c.currency)}</td>
                    <td className="small">{c.shared_identifiers.join(", ")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

        </div>
      )}
    </div>
  );
}
