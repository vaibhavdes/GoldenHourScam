import { useEffect, useState } from "react";
import type { Field } from "../lib/api";
import { u } from "../lib/i18n";
import { useApp } from "../lib/state";

export function CopyButton({ text, label = "Copy", done = "Copied" }: { text: string; label?: string; done?: string }) {
  const { lang } = useApp();
  const [ok, setOk] = useState(false);
  const [error, setError] = useState(false);
  return (
    <><button
      className="ghost small"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setOk(true);
          setError(false);
          setTimeout(() => setOk(false), 1500);
        } catch {
          setError(true);
        }
      }}
    >
      {u(lang, ok ? done : label)}
    </button>{error && <span role="alert" className="issue">{u(lang, "Could not copy. Select the text and copy it manually.")}</span>}</>
  );
}

/** Live "time since first transfer" clock - the golden-hour timer. */
export function GoldenTimer({ since, label }: { since?: string | null; label: string }) {
  const [, tick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => tick((x) => x + 1), 1000);
    return () => clearInterval(id);
  }, []);
  if (!since) return null;
  const ms = Date.now() - new Date(since).getTime();
  if (Number.isNaN(ms) || ms < 0) return null;
  const h = Math.floor(ms / 3600000);
  const m = Math.floor((ms % 3600000) / 60000);
  const s = Math.floor((ms % 60000) / 1000);
  const pad = (n: number) => n.toString().padStart(2, "0");
  return (
    <div role="timer" aria-live="off">
      <div className="timer">
        {h > 0 ? `${h}:` : ""}
        {pad(m)}:{pad(s)}
      </div>
      <div className="muted small">{label}</div>
    </div>
  );
}

/** Shows the source text with the extracted value highlighted (grounding made visible). */
export function SourceQuote({ f }: { f: Field }) {
  if (!f.source_quote || f.source_file === "user") return null;
  const q = f.source_quote;
  const v = f.value ?? "";
  const i = v ? q.toLowerCase().indexOf(v.toLowerCase()) : -1;
  return (
    <div className="quote">
      {f.source_file ? `${f.source_file.replace(/^[0-9a-f]{8,}\s+/i, "")}: ` : ""}“
      {i >= 0 ? (
        <>
          {q.slice(0, i)}
          <mark>{q.slice(i, i + v.length)}</mark>
          {q.slice(i + v.length)}
        </>
      ) : (
        q
      )}
      ”
    </div>
  );
}

export function Confidence({ f }: { f: Field }) {
  const { lang } = useApp();
  const label = f.status === "user" ? "entered by you" : f.status === "checked" ? "checked" : f.status === "read" ? "read · please check" : "missing";
  return <span className={`pill ${f.status === "user" ? "amber" : f.valid ? "green" : "red"}`}>{u(lang, label)}</span>;
}

export function Spinner({ text }: { text?: string }) {
  return (
    <div className="row" role="status">
      <div className="spinner" /> {text}
    </div>
  );
}

export const SCAM_LABELS: Record<string, string> = {
  investment: "Fake investment",
  digital_arrest: "Digital arrest / fake police",
  task_job: "Task / job scam",
  sextortion: "Sextortion",
  phishing_otp: "Phishing / OTP",
  impersonation: "Impersonation",
  shopping: "Shopping scam",
  recovery_scam: "Fake recovery agent",
  unknown: "Unclassified",
};
