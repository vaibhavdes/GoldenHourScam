import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import { Spinner } from "../components/ui";

type Pattern = Awaited<ReturnType<typeof api.patterns>>[number];
export default function Patterns() {
  const [items, setItems] = useState<Pattern[] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    api.patterns().then(data => { if (active) setItems(data); }).catch(e => { if (active) setError(e.message); });
    return () => { active = false; };
  }, []);
  return <div className="stack">
    <h1>Recognise the warning signs</h1>
    <p className="muted">Common situations described in official scam advisories. If you have already paid, contact your bank and reporting helpline immediately.</p>
    <div className="row"><Link className="btn" to="/">Prepare your report</Link><Link to="/check">Check a message or call</Link></div>
    {error && <p role="alert" className="issue">{error}</p>}
    {!items && !error && <Spinner text="Loading guidance…" />}
    <div className="grid2">{items?.map(item => <article className="card stack" key={item.id}>
      <h2>{item.title}</h2><p>{item.signs}</p><p className="small"><b>What to do:</b> {item.action}</p>
      <a className="small" href={item.url} target="_blank" rel="noreferrer">Read the {item.source} advisory ↗</a>
    </article>)}</div>
  </div>;
}
