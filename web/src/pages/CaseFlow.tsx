import { downloadDeadlines } from "../lib/calendar";
import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { useParams, useSearchParams, Link } from "react-router-dom";
import { Confidence, CopyButton, GoldenTimer, SCAM_LABELS, SourceQuote, Spinner } from "../components/ui";
import { api, type Case, type FilingPack, type Field, type Step, type Transaction } from "../lib/api";
import { t, u } from "../lib/i18n";
import { FALLBACK_PACKS, fmtMoney, useApp } from "../lib/state";
import { VoiceSession, type VoiceEvent } from "../lib/voice";

type Tab = "call" | "upload" | "review" | "pack" | "voice" | "track";

export default function CaseFlow() {
  const { id = "" } = useParams();
  const [search] = useSearchParams();
  const { lang, packs, country } = useApp();
  const [c, setC] = useState<Case | null>(null);
  const [tab, setTab] = useState<Tab>(search.get("step") === "review" ? "review" : "call");
  const [err, setErr] = useState("");

  const reload = useCallback(() => api.getCase(id).then(setC).catch((e) => setErr(e.message)), [id]);
  useEffect(() => {
    let active = true;
    setC(null); setErr(""); setTab(search.get("step") === "review" ? "review" : "call");
    api.getCase(id).then(data => { if (active) setC(data); }).catch(e => { if (active) setErr(e.message); });
    return () => { active = false; };
  }, [id]);
  useEffect(() => {
    if (c && c.language !== lang) api.language(c.id, lang).then(setC).catch(e => setErr(e.message));
  }, [c?.id, c?.language, lang]);

  const firstTxn = useMemo(() => {
    const times = (c?.transactions ?? []).filter(x => x.direction === "debit" && x.timestamp.valid).map((x) => x.timestamp.value).filter(Boolean) as string[];
    return times.sort((a, b) => new Date(a).getTime() - new Date(b).getTime())[0] ?? (c?.reported_transfer_time?.valid ? c.reported_transfer_time.value : undefined);
  }, [c]);

  if (err && !c) {
    const emergency = FALLBACK_PACKS.find(p => p.code === country)?.helplines.find(h => h.primary);
    return <div className="stack">{emergency && <a className="btn call" href={`tel:${emergency.number}`}>{t(lang, "callNow")} {emergency.number}</a>}<p className="issue">{err}</p></div>;
  }
  if (!c) return <Spinner text={u(lang, "Loading\u2026" )} />;
  const pack = packs.find(p => p.code === c.country) ?? FALLBACK_PACKS.find(p => p.code === c.country);
  const primary = pack?.helplines.find((h) => h.primary);

  const tabs: [Tab, string][] = [
    ["call", t(lang, "step1")],
    ["upload", t(lang, "step2")],
    ["review", t(lang, "step3")],
    ["pack", t(lang, "step4")],
    ["voice", u(lang, "🎙️ Voice")],
    ["track", u(lang, "Track")],
  ];

  const progressStep = tabs.slice(0, 4).findIndex(([key]) => key === tab) + 1;

  return (
    <div>

      {err && <p role="alert" className="issue">{err}</p>}
      {progressStep > 0 && <div className="progress"><label>{lang === "hi" ? `चरण ${progressStep} / 4` : `Step ${progressStep} of 4`}</label><progress max={4} value={progressStep} /></div>}
      <div className="row" style={{ justifyContent: "space-between" }}>
        <div>
          <div className="muted small">{u(lang, "Case")} {c.id} · {pack?.name ?? c.country}</div>
          {c.scam_type !== "unknown" && <span className="pill red">{u(lang, SCAM_LABELS[c.scam_type])}</span>}
        </div>
        {firstTxn ? <GoldenTimer since={firstTxn} label={t(lang, "sinceFirst")} /> : <TransferTime c={c} onChange={setC} />}
      </div>
      <details className="allsteps">
        <summary>{lang === "hi" ? "सभी चरण देखें" : "All steps"}</summary>
        <nav className="steps" aria-label="Steps">
          {tabs.map(([k, label]) => (
            <button key={k} className="ghost" aria-current={tab === k ? "step" : undefined} onClick={() => setTab(k)}>
              {label}
            </button>
          ))}
        </nav>
      </details>
      {tab !== "voice" && <button className="ghost small voicecta" onClick={() => setTab("voice")}>🎙️ {lang === "hi" ? "बोलकर मदद लें" : "Need help? Talk to GoldenHour"}</button>}

      {tab === "call" && (
        <div className="stack">
          {c.country === "SG" && <p className="card alert">First: call your bank’s 24/7 anti-scam hotline or use its kill switch. Then call 1799 and lodge the police report.</p>}
          {primary && (
            <a className={`btn ${c.country === "SG" ? "ghost" : "call"}`} href={`tel:${primary.number}`}>
              📞 {t(lang, "callNow")} {primary.number}
            </a>
          )}
          <p className="muted small">{lang === "hi" ? "स्पीकर चालू करके यह स्क्रीन खुली रखें। स्क्रीनशॉट डालने के बाद शिकायत पैक में बताने वाली जानकारी मिलेगी।" : "Keep this screen open on speaker. After uploading, your complaint pack contains the call script."}</p>
          <Checklist c={c} onChange={setC} />
          <button onClick={() => setTab("upload")}>{u(lang, "Next: upload screenshots")} →</button>
        </div>
      )}
      {tab === "upload" && <Upload key={c.id} c={c} onDone={(nc) => (setC(nc), setTab("review"))} />}
      {tab === "review" && <Review key={c.id} c={c} onDone={(nc) => (setC(nc), setTab("pack"))} />}
      {tab === "pack" && !c.transactions.length && <div className="card stack"><p>{lang === "hi" ? "पहले अपने भुगतान का स्क्रीनशॉट डालें या विवरण स्वयं भरें।" : "Add a payment screenshot or enter the transfer details first. Your complaint pack is built from them."}</p><button onClick={() => setTab("upload")}>{u(lang, "Next: upload screenshots")} →</button></div>}
      {tab === "pack" && c.transactions.length > 0 && <><PackView key={c.id} c={c} /><button onClick={() => setTab("track")}>{lang === "hi" ? "अगला: पावती और स्थिति" : "Next: acknowledgement and tracking"} →</button></>}
      {tab === "voice" && <Voice key={c.id} c={c} onToolChange={reload} />}
      {tab === "track" && <Track key={c.id} c={c} onChange={setC} />}
    </div>
  );
}

function TransferTime({ c, onChange }: { c: Case; onChange: (c: Case) => void }) {
  const { lang } = useApp();
  const [time, setTime] = useState("");
  const [error, setError] = useState("");
  return <details className="small">
    <summary>{u(lang, "Transfer time unknown")}</summary>
    <label>{u(lang, "When did you send the money? (optional)")} · UTC{c.country === "IN" ? "+05:30" : "+08:00"}<input type="datetime-local" value={time} onChange={e => setTime(e.target.value)} />
    </label>
    <button className="ghost small" disabled={!time} onClick={async () => {
      try { onChange(await api.transferTime(c.id, time + (time.length === 16 ? ":00" : "") + (c.country === "IN" ? "+05:30" : "+08:00"))); }
      catch (e) { setError((e as Error).message); }
    }}>{u(lang, "Save transfer time")}</button>
    {error && <p className="issue">{error}</p>}
  </details>;
}

function ReadingProgress({ count }: { count: number }) {
  const { lang } = useApp();
  const [secs, setSecs] = useState(0);
  useEffect(() => { const id = setInterval(() => setSecs(x => x + 1), 1000); return () => clearInterval(id); }, []);
  const stages = lang === "hi"
    ? ["फ़ाइलें भेजी जा रही हैं…", `${count} स्क्रीनशॉट पढ़े जा रहे हैं…`, "हर जानकारी को दोबारा अलग से जाँचा जा रहा है…", "लगभग हो गया…"]
    : ["Uploading your files…", `Reading ${count} screenshot${count === 1 ? "" : "s"} with Gemini…`, "Double-checking every number against your screenshots…", "Almost done…"];
  const stage = secs < 4 ? 0 : secs < 25 ? 1 : secs < 50 ? 2 : 3;
  return (
    <div className="card" role="status" aria-live="polite">
      <Spinner text={stages[stage]} />
      <progress max={60} value={Math.min(secs, 58)} style={{ width: "100%" }} />
      <p className="small muted">{lang === "hi" ? "इसमें लगभग एक मिनट लगता है। इस बीच हेल्पलाइन पर कॉल कर सकते हैं — यह स्क्रीन खुली रखें।" : "This takes about a minute. You can stay on the helpline call meanwhile — keep this screen open."} ({secs}s)</p>
    </div>
  );
}

function Checklist({ c, onChange }: { c: Case; onChange: (c: Case) => void }) {
  const { lang } = useApp();
  const [error, setError] = useState("");
  return (
    <div className="card">
      {[["core", c.steps.filter(s => !s.id.startsWith("lock_"))], ["lock", c.steps.filter(s => s.id.startsWith("lock_"))]].map(([group, items]) => (items as Step[]).length > 0 && (
        <details key={group as string} open={group === "core"}>
          <summary><b>{group === "core" ? (lang === "hi" ? "आपके कदम" : "Your steps") : (lang === "hi" ? "अपने खाते सुरक्षित करें" : "Protect your accounts")}</b></summary>
          {(items as Step[]).map((s) => (
            <label key={s.id} className="check">
              <input type="checkbox" checked={s.done} onChange={(e) => api.step(c.id, s.id, e.target.checked).then(onChange).catch(e => setError(e.message))} />
              <span>{s.label}</span>
            </label>
          ))}
        </details>
      ))}
      {error && <p className="issue">{error}</p>}
    </div>
  );
}

// Fictional, watermarked evidence so anyone can try the real reading pipeline without personal data.
const SAMPLE_SETS: { id: string; country: string; title: string; titleHi: string; files: string[] }[] = [
  { id: "in-digital-arrest", country: "IN", title: "Fake police “digital arrest” · ₹4.85 lakh · Hindi chat", titleHi: "नकली पुलिस “डिजिटल अरेस्ट” · ₹4.85 लाख · हिंदी चैट", files: ["sms_1.png", "sms_2.png", "receipt_1.png", "receipt_2.png", "chat.png"] },
  { id: "in-investment", country: "IN", title: "Fake trading group · ₹56,000 · same scammer UPI ID", titleHi: "नकली ट्रेडिंग ग्रुप · ₹56,000 · वही ठग UPI ID", files: ["sms_1.png", "receipt_1.png", "sms_2.png", "receipt_2.png", "chat.png"] },
  { id: "my-investment", country: "MY", title: "Investment scam via DuitNow · RM64,900 · Malay chat", titleHi: "DuitNow निवेश धोखाधड़ी · मलेशिया", files: ["sms_1.png", "receipt_1.png", "sms_2.png", "receipt_2.png", "chat.png"] },
];

async function loadSample(id: string, names: string[]): Promise<File[]> {
  return Promise.all(names.map(async name => {
    const blob = await (await fetch(`/samples/${id}/${name}`)).blob();
    return new File([blob], `sample-${name}`, { type: "image/png" });
  }));
}

function Upload({ c, onDone }: { c: Case; onDone: (c: Case) => void }) {
  const { lang } = useApp();
  const [files, setFiles] = useState<File[]>([]);
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [over, setOver] = useState(false);
  const [err, setErr] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const previews = useMemo(() => files.map(file => file.type.startsWith("image/") ? URL.createObjectURL(file) : null), [files]);
  useEffect(() => () => previews.forEach(url => { if (url) URL.revokeObjectURL(url); }), [previews]);

  const add = (list: FileList | null) => {
    const selected = Array.from(list ?? []);
    setFiles(current => [...current, ...selected].slice(0, 10));
  };

  async function go() {
    setBusy(true);
    setErr("");
    try {
      const r = await api.upload(c.id, files, notes);
      onDone(r.case);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="stack">
      <p>{t(lang, "uploadHint")}</p>
      <div
        className={`drop ${over ? "on" : ""}`}
        role="button"
        tabIndex={0}
        onClick={() => input.current?.click()}
        onKeyDown={(e) => e.key === "Enter" && input.current?.click()}
        onDragOver={(e) => (e.preventDefault(), setOver(true))}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => (e.preventDefault(), setOver(false), add(e.dataTransfer.files))}
      >{u(lang, "📷 Tap to add screenshots / PDF")}<input ref={input} type="file" hidden multiple accept="image/png,image/jpeg,image/webp,image/heic,application/pdf,text/plain" onChange={(e) => { add(e.target.files); e.target.value = ""; }} />
      </div>
      {files.length === 0 && SAMPLE_SETS.some(x => x.country === c.country) && (
        <details className="samples">
          <summary>{lang === "hi" ? "स्क्रीनशॉट नहीं हैं? काल्पनिक नमूना आज़माएँ" : "No screenshots to hand? Try fictional sample evidence"}</summary>
          <p className="small muted">{lang === "hi" ? "ये काल्पनिक, “SYNTHETIC” चिह्नित स्क्रीनशॉट हैं। Gemini इन्हें असली प्रक्रिया से पढ़ेगा।" : "Fictional screenshots marked “SYNTHETIC”. Gemini reads them through the same real pipeline as your own evidence."}</p>
          {SAMPLE_SETS.filter(x => x.country === c.country).map(set => (
            <button key={set.id} className="ghost small sample" disabled={busy} onClick={async () => {
              try { setFiles(await loadSample(set.id, set.files)); } catch { setErr("Could not load the sample. Check your connection."); }
            }}>{lang === "hi" ? set.titleHi : set.title}</button>
          ))}
        </details>
      )}
      {files.length > 0 && (
        <div className="thumbs">
          {files.map((f, i) => <div key={i} className="stack" style={{ gap: 4 }}>
            {f.type.startsWith("image/") ? <img src={previews[i]!} alt={f.name} /> : <span className="pill">{f.name}</span>}
            <button className="ghost small" disabled={busy} aria-label={`Remove ${f.name}`} onClick={() => setFiles(current => current.filter((_, index) => index !== i))}>{lang === "hi" ? "हटाएँ" : "Remove"}</button>
          </div>)}
        </div>
      )}
      <label className="small muted">{u(lang, "Anything else? (optional) - who contacted you, what they said")}<textarea value={notes} onChange={(e) => setNotes(e.target.value)} />
      </label>
      <button disabled={!files.length || busy} onClick={go}>
        {t(lang, "analyse")}
      </button>
      {busy && <ReadingProgress count={files.length} />}
      {err && <p role="alert" className="issue">{err}</p>}
      <button className="ghost" disabled={busy} onClick={() => onDone(c)}>{lang === "hi" ? "रसीद से जानकारी स्वयं भरें" : "Enter details from your receipt manually"}</button>
      <p className="muted small">{u(lang, "Your files are used only for this case. A 30-day expiry policy applies; deletion can take additional time.")}</p>
    </div>
  );
}

function FieldEdit({ label, f, onChange, datetimeOffset }: { label: string; f: Field; onChange: (v: string) => void; datetimeOffset?: string }) {
  const { lang } = useApp();
  const inputId = useId();
  const offsetMinutes = datetimeOffset === "+05:30" ? 330 : 480;
  const localTime = f.value && Number.isFinite(Date.parse(f.value))
    ? new Date(Date.parse(f.value) + offsetMinutes * 60000).toISOString().slice(0, 16) : "";
  return (
    <div className="field">
      <label htmlFor={inputId}>
        {label} <Confidence f={f} />
      </label>
      <input id={inputId} type={datetimeOffset ? "datetime-local" : "text"}
        value={datetimeOffset ? localTime : f.value ?? ""}
        onChange={(e) => onChange(datetimeOffset && e.target.value
          ? e.target.value + (e.target.value.length === 16 ? ":00" : "") + datetimeOffset : e.target.value)} />
      {datetimeOffset && <p className="muted small">{lang === "hi" ? "रसीद में दिखा स्थानीय समय" : "Local time shown on the receipt"} · UTC{datetimeOffset}</p>}
      <SourceQuote f={f} />
      {f.issue && <div className="issue">{f.issue}</div>}
    </div>
  );
}

function Review({ c, onDone }: { c: Case; onDone: (c: Case) => void }) {
  const { lang } = useApp();
  const [txns, setTxns] = useState<Transaction[]>(c.transactions);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const total = txns.filter(x => x.direction === "debit").reduce((s, x) => s + (parseFloat(x.amount.value ?? "0") || 0), 0);

  const set = (i: number, path: string, v: string) =>
    setTxns((ts) =>
      ts.map((tx, j) => {
        if (j !== i) return tx;
        const copy = structuredClone(tx);
        const parts = path.split(".");
        let o: any = copy;
        for (const p of parts.slice(0, -1)) o = o[p];
        o[parts.at(-1)!] = { ...o[parts.at(-1)!], value: v, source_quote: null, source_file: null, status: "user", valid: false, issue: null };
        return copy;
      }),
    );

  const addTransfer = () => {
    const empty = (): Field => ({ value: null, confidence: 0, valid: false, status: "missing" });
    setTxns(items => [...items, { id: crypto.randomUUID().slice(0, 8), currency: c.country === "MY" ? "MYR" : c.country === "SG" ? "SGD" : "INR", rail: "UNKNOWN", direction: "debit", confirmed: false,
      amount: empty(), utr: empty(), timestamp: empty(), victim_account_masked: empty(),
      beneficiary: { vpa: empty(), account: empty(), ifsc: empty(), bank: empty(), name: empty() } }]);
  };

  return (
    <div className="stack">
      {!txns.length && <p>{lang === "hi" ? "ट्रांसफर नहीं मिला। स्क्रीनशॉट डालें या रसीद से जानकारी स्वयं भरें।" : "No transfers found. Upload a receipt or enter its details yourself."}</p>}
      {c.explanation && (
        <div className="card alert">
          <b>{t(lang, "notYourFault")}</b>
          <p>{c.explanation}</p>
          {c.red_flags.length > 0 && (
            <ul className="small">
              {c.red_flags.map((r) => (
                <li key={r}>{r}</li>
              ))}
            </ul>
          )}
        </div>
      )}
      {txns.length > 0 && <p>
        <b>{txns.length}</b> {u(lang, "transfer(s)")}, {u(lang, "total")} <b>{fmtMoney(total, txns[0]?.currency ?? "INR")}</b>. {u(lang, "Read and confirm each value before using the draft.")}
      </p>}
      {txns.map((tx, i) => (
        <div className="card" key={tx.id}>
          <h3>
            {u(lang, "Transfer")} {i + 1} · {tx.rail}
            {tx.direction === "credit" && <span className="pill">{lang === "hi" ? "जमा / वापसी — नुकसान में शामिल नहीं" : "Credit / refund — excluded from loss"}</span>}
          </h3>
          <div className="row"><button className="ghost small" onClick={() => setTxns(items => items.filter((_, j) => j !== i))}>{lang === "hi" ? "यह ट्रांसफर हटाएँ" : "Remove this transfer"}</button></div>
          <label>{lang === "hi" ? "भुगतान का तरीका" : "Payment method"}
            <select value={tx.rail} onChange={e => setTxns(ts => ts.map((item, j) => j === i ? { ...item, rail: e.target.value as Transaction["rail"] } : item))}>
              {["UPI", "IMPS", "NEFT", "RTGS", "CARD", "WALLET", "CRYPTO", "GIFT_CARD", "DUITNOW", "PAYNOW", "BANK_TRANSFER", "UNKNOWN"].map(rail => <option key={rail} value={rail}>{rail}</option>)}
            </select>
          </label>
          <FieldEdit label={u(lang, "Amount" )} f={tx.amount} onChange={(v) => set(i, "amount", v)} />
          <FieldEdit label={u(lang, "Transaction ID / UTR" )} f={tx.utr} onChange={(v) => set(i, "utr", v)} />
          <FieldEdit label={u(lang, "Date & time" )} f={tx.timestamp} datetimeOffset={c.country === "IN" ? "+05:30" : "+08:00"} onChange={(v) => set(i, "timestamp", v)} />
          <FieldEdit label={u(lang, "Your account" )} f={tx.victim_account_masked} onChange={(v) => set(i, "victim_account_masked", v)} />
          <FieldEdit label={u(lang, "Sent to (UPI ID)" )} f={tx.beneficiary.vpa} onChange={(v) => set(i, "beneficiary.vpa", v)} />
          {tx.rail !== "UPI" && (
            <>
              <FieldEdit label={u(lang, "Sent to (account)" )} f={tx.beneficiary.account} onChange={(v) => set(i, "beneficiary.account", v)} />
              <FieldEdit label="IFSC" f={tx.beneficiary.ifsc} onChange={(v) => set(i, "beneficiary.ifsc", v)} />
            </>
          )}
        </div>
      ))}
      <button className="ghost" onClick={addTransfer}>{lang === "hi" ? "ट्रांसफर की जानकारी स्वयं भरें" : "Enter another transfer manually"}</button>
      {c.suspects.length > 0 && (
        <div className="card">
          <h3>{u(lang, "Fraudster details")}</h3>
          {c.suspects.map((s, i) => (
            <p key={i} className="small">
              {[s.claimed_identity, s.phone, s.platform, s.url, s.handle].filter(Boolean).join(" · ")}
            </p>
          ))}
        </div>
      )}
      <button
        disabled={busy || txns.length === 0}
        onClick={async () => {
          setBusy(true);
          try {
            onDone(await api.confirm(c.id, txns, c.suspects));
          } catch (e) {
            setError((e as Error).message);
          } finally {
            setBusy(false);
          }
        }}
      >
        ✓ {t(lang, "confirm")}
      </button>
      {error && <p className="issue">{error}</p>}
    </div>
  );
}

function PackView({ c }: { c: Case }) {
  const { lang } = useApp();
  const [p, setP] = useState<FilingPack | null>(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    api.pack(c.id).then(setP).catch((e) => setErr(e.message));
  }, [c.id]);
  if (err) return <p className="issue">{err}</p>;
  if (!p) return <Spinner text={u(lang, "Preparing your complaint pack\u2026" )} />;
  return (
    <div className="stack">
      <p className="small">{u(lang, "The complaint pack below is in English for reporting. Review it before copying.")}</p>
      <p role="status" className={p.ready ? "pill green" : "pill amber"}>{p.ready ? u(lang, "Reviewed report ready") : u(lang, "Draft — review missing details and confirm transfers")}</p>
      {p.missing.length > 0 && (
        <div className="card alert">
          {p.ready ? (lang === "hi" ? "वैकल्पिक जानकारी जोड़ें" : "Optional details to add") : u(lang, "Still needed")}: {p.missing.map(item => u(lang, item)).join(", ")}. {lang === "hi" ? "चरण 3 में जाँचकर सुधारें।" : "Review and correct these in step 3."}
        </div>
      )}
      <div className="card">
        <h2>{u(lang, "☎️ What the helpline will ask")}</h2>
        {p.call_script.map((s, i) => (
          <div key={i} className="field">
            <label>{s.q}</label>
            <div className="val">
              <code>{s.a}</code>
            </div>
          </div>
        ))}
      </div>
      <div className="card">
        <h2>📝 {p.portal_name}</h2>
        {p.country === "MY" ? <p className="small">
          {lang === "ms" ? "Selepas menghubungi bank atau NSRC 997, bawa draf ini dan bukti ke balai polis terdekat untuk laporan berasingan dalam 24 jam. " : "After contacting your bank or NSRC 997, take this draft and your evidence to the nearest police station for a separate report within 24 hours. "}
          <a href={p.portal_url} target="_blank" rel="noreferrer">{lang === "ms" ? "Panduan rasmi" : "Official reporting guidance"}</a>
        </p> : <p className="small">{u(lang, "Open")}<a href={p.portal_url} target="_blank" rel="noreferrer">{p.portal_url}</a> {lang === "hi" ? "और जानकारी सही बॉक्स में कॉपी करें।" : "and copy each item into the matching box."}</p>}
        {p.fields.map((f) => (
          <div className="field" key={f.key}>
            <label>
              {f.label} {f.required && <span className="muted">*</span>} {!f.ok && <span className="pill red">{u(lang, f.required ? "needed" : "missing")}</span>}
            </label>
            <div className="val">
              <code>{f.value || "-"}</code>
              {f.ok && f.value && <CopyButton text={f.value} label={t(lang, "copy")} done={t(lang, "copied")} />}
            </div>
            {f.hint && <div className="issue">{f.hint}</div>}
          </div>
        ))}
        <div className="field">
          <label>
            {u(lang, "Incident description")} {p.narrative_ok ? <span className="pill green">{p.country === "MY" ? (lang === "ms" ? "draf disemak" : "reviewed draft") : u(lang, "portal-ready")}</span> : <span className="pill red">{u(lang, "check")}</span>}
          </label>
          <pre className="letter">{p.narrative}</pre>
          <CopyButton text={p.narrative} label={t(lang, "copy")} done={t(lang, "copied")} />
        </div>
      </div>
      <div className="card">
        <h2>{u(lang, "🏦 Letter to your bank")}</h2>
        <pre className="letter">{p.bank_letter}</pre>
        <CopyButton text={p.bank_letter} label={t(lang, "copy")} done={t(lang, "copied")} />
      </div>
      <div className="card">
        <h2>{u(lang, "📎 Evidence to attach")}</h2>
        {p.evidence_checklist.map((e, i) => (
          <p key={i} className="small">
            {e.ok === null ? "◻️" : e.ok ? "✅" : "⚠️"} {u(lang, e.file)} {e.note && <span className="muted">- {u(lang, e.note)}</span>}
          </p>
        ))}
      </div>
      <p className="muted small">{lang === "hi" ? "यह केवल शिकायत का मसौदा है। आप स्वयं जाँचकर शिकायत भेजें। GoldenHour आपकी ओर से शिकायत नहीं करता, किसी से संपर्क नहीं करता और पैसे वापस मिलने की गारंटी नहीं देता।" : p.disclaimer}</p>
    </div>
  );
}

function Voice({ c, onToolChange }: { c: Case; onToolChange: () => void }) {
  const { lang } = useApp();
  const [state, setState] = useState<"idle" | "connecting" | "live" | "closed">("idle");
  const [lines, setLines] = useState<{ role: string; text: string }[]>([]);
  const [err, setErr] = useState("");
  const [question, setQuestion] = useState("");
  const [answering, setAnswering] = useState(false);
  const sess = useRef<VoiceSession | null>(null);

  useEffect(() => () => sess.current?.stop(), []);
  useEffect(() => {
    if (!answering) return;
    const timeout = setTimeout(() => { sess.current?.stop(); setAnswering(false); setErr(lang === "hi" ? "जवाब आने में देर हो रही है। चेकलिस्ट का उपयोग करें।" : "The answer is taking too long. Use the checklist and call guidance."); }, 60000);
    return () => clearTimeout(timeout);
  }, [answering, lang]);

  const onEvent = (e: VoiceEvent) => {
    if (e.type === "state") setState(e.state);
    else if (e.type === "error") setErr(lang === "hi" ? "आवाज़ का कनेक्शन नहीं हुआ। चेकलिस्ट का उपयोग करें और हेल्पलाइन पर कॉल करें।" : e.message);
    else if (e.type === "tool") onToolChange();
    else if (e.type === "transcript")
      setLines((ls) => {
        const last = ls.at(-1);
        if (last && last.role === e.role) return [...ls.slice(0, -1), { role: e.role, text: last.text + e.text }];
        return [...ls, { role: e.role, text: e.text }];
      });
    else if (e.type === "turn_complete") setAnswering(false);
    if (e.type === "error" || (e.type === "state" && e.state === "closed")) setAnswering(false);
  };

  async function toggle() {
    if (state === "live" || state === "connecting") {
      sess.current?.stop();
      setState("closed");
      return;
    }
    setErr("");
    sess.current = new VoiceSession(c.id, lang, onEvent);
    try {
      await sess.current.start();
    } catch (e) {
      setErr(lang === "hi" ? "माइक्रोफ़ोन उपलब्ध नहीं है। अनुमति जाँचें या चेकलिस्ट का उपयोग करें।" : "Microphone unavailable. Check permission or use the checklist.");
      setState("idle");
    }
  }

  return (
    <div className="stack" style={{ justifyItems: "center", textAlign: "center" }}>
      <p>{t(lang, "voice")} — {lang === "hi" ? "अपनी भाषा में बात करें।" : "speak in your own language."}</p>
      <button className={`mic ${state === "live" ? "live" : ""}`} onClick={toggle} aria-label={u(lang, "Start or stop voice" )}>
        {state === "live" ? "■" : "🎙️"}
      </button>
      <p className="muted small">{state === "live" ? u(lang, "Listening…") : state === "connecting" ? u(lang, "Connecting…") : u(lang, "Tap to talk")}</p>
      {err && <p className="issue">{err}</p>}
      <div className="card stack" style={{ width: "100%", textAlign: "left" }}>
        <label>{lang === "hi" ? "माइक्रोफ़ोन के बिना सवाल लिखें" : "Type a question without a microphone"}<textarea maxLength={2000} value={question} onChange={e => setQuestion(e.target.value)} /></label>
        <button disabled={!question.trim() || state === "connecting" || answering} onClick={async () => {
          setErr(""); setAnswering(true);
          try {
            if (state !== "live") { sess.current?.stop(); setAnswering(true); sess.current = new VoiceSession(c.id, lang, onEvent); await sess.current.start(false); }
            sess.current?.sendText(question.trim());
            setLines(ls => [...ls, { role: "user", text: question.trim() }]); setQuestion("");
          } catch { setAnswering(false); setErr(lang === "hi" ? "कनेक्शन नहीं हुआ। चेकलिस्ट का उपयोग करें।" : "Could not connect. Use the checklist and call guidance."); }
        }}>{answering ? (lang === "hi" ? "जवाब आ रहा है…" : "Waiting for answer…") : (lang === "hi" ? "सवाल पूछें" : "Ask without microphone")}</button>
      </div>
      <div className="transcript" style={{ width: "100%" }}>
        {lines.map((l, i) => (
          <div key={i} className={`bubble ${l.role}`}>
            {l.text}
          </div>
        ))}
      </div>
    </div>
  );
}

function Track({ c, onChange }: { c: Case; onChange: (c: Case) => void }) {
  const { lang } = useApp();
  const [ack, setAck] = useState(c.ack_number ?? "");
  const [saving, setSaving] = useState(false);
  const [rem, setRem] = useState<{ id: string; due_at: string; text: string; schedule_status?: string }[]>([]);
  const [error, setError] = useState("");
  const [share, setShare] = useState("");
  const [restoration, setRestoration] = useState<string | null>(null);

  useEffect(() => {
    api.reminders(c.id).then(setRem).catch(() => {});
    api.restoration(c.id).then((p) => setRestoration(p.restoration_request ?? null)).catch(e => setError(e.message));
  }, [c.id, c.ack_number]);

  return (
    <div className="stack">
      <div className="card">
        <h3>{u(lang, "Acknowledgement number")}</h3>
        <p className="small muted">{lang === "hi" ? "हेल्पलाइन से मिली पावती संख्या यहाँ डालें।" : "Enter the acknowledgement number received from the helpline."}</p>
        <div className="row">
          <input aria-label={u(lang, "Acknowledgement number")} value={ack} onChange={(e) => setAck(e.target.value)} placeholder={lang === "hi" ? "जैसे 31610260012345" : "e.g. 31610260012345"} style={{ flex: 1 }} />
          <button className="small"
            disabled={saving || !ack.trim()}
            onClick={async () => {
              try {
              setSaving(true); setError("");
              const r = await api.ack(c.id, ack);
              onChange(r.case);
              setRem(r.reminders);
              } catch (e) { setError((e as Error).message); } finally { setSaving(false); }
            }}
          >{saving ? u(lang, "Saving…") : u(lang, "Save")}</button>
        </div>
      </div>
      <div className="card">
        <h3>{u(lang, "⏰ Next deadlines")}</h3>
        <p className="small muted">{lang === "hi" ? "ये तारीखें यहाँ देखें या अपने कैलेंडर में जोड़ें। SMS या WhatsApp संदेश नहीं भेजे जाते।" : "View these dates here or add them to your calendar. No SMS or WhatsApp messages are sent."}</p>
        {rem.length === 0 && <p className="muted small">{lang === "hi" ? "अनुवर्ती तारीखें देखने के लिए पावती संख्या सहेजें।" : "Save your acknowledgement number to see the follow-up dates."}</p>}
        {rem.length > 0 && <button className="ghost small" onClick={() => downloadDeadlines(c.id, rem)}>{lang === "hi" ? "कैलेंडर में जोड़ें" : "Add to calendar"}</button>}
        {rem.map((r) => (
          <p key={r.id} className="small">
            <b>{new Date(r.due_at).toLocaleString()}</b> - {r.text}
          </p>
        ))}
      </div>
      {restoration && (
        <div className="card">
          <h3>{u(lang, "💰 Getting money back (restoration request)")}</h3>
          <pre className="letter">{restoration}</pre>
          <CopyButton text={restoration} label={t(lang, "copy")} done={t(lang, "copied")} />
        </div>
      )}
      <div className="card">
        <h3>👪 {t(lang, "share")}</h3>
        <button className="ghost small"
          onClick={async () => {
            try {
            const r = await api.share(c.id);
            setShare(`${location.origin}/h/${r.token}`);
            } catch (e) { setError((e as Error).message); }
          }}
        >{u(lang, "Create 24-hour link")}</button>
        {share && (
          <div className="val row">
            <code style={{ overflowWrap: "anywhere" }}>{share}</code>
            <CopyButton text={share} />
          </div>
        )}
      </div>
      <div className="card alert">
        <b>{u(lang, "🛡️ Beware of \"recovery agents\".")}</b> {lang === "hi" ? "पैसे वापस दिलाने के लिए शुल्क माँगने वाले को भुगतान न करें।" : "Do not pay anyone asking for a fee to recover your money."}
      </div>
      {error && <p role="alert" className="issue">{error}</p>}
    </div>
  );
}
