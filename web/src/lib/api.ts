// Typed client for the GoldenHour API.
export const API_BASE: string = import.meta.env.VITE_API_BASE ?? "/api";

export type Field = {
  value: string | null;
  confidence: number;
  source_quote?: string | null;
  source_file?: string | null;
  valid: boolean;
  status: "read" | "checked" | "user" | "missing";
  issue?: string | null;
};
export type Beneficiary = { vpa: Field; account: Field; ifsc: Field; bank: Field; name: Field };
export type Transaction = {
  id: string;
  amount: Field;
  currency: string;
  rail: string;
  utr: Field;
  timestamp: Field;
  victim_account_masked: Field;
  beneficiary: Beneficiary;
  direction: "debit" | "credit";
  confirmed: boolean;
};
export type Suspect = { phone?: string; url?: string; handle?: string; platform?: string; claimed_identity?: string };
export type Step = { id: string; label: string; done: boolean; done_at?: string | null };
export type Case = {
  id: string;
  country: string;
  language: string;
  stage: string;
  created_at: string;
  scam_type: string;
  scam_type_confidence: number;
  red_flags: string[];
  explanation?: string | null;
  transactions: Transaction[];
  suspects: Suspect[];
  evidence: { id: string; filename: string; size_bytes: number }[];
  steps: Step[];
  ack_number?: string | null;
  reported_at?: string | null;
  reported_transfer_time?: Field;
  timeline: { time: string; event: string }[];
  synthetic: boolean;
};
export type Helpline = { id: string; label: string; number: string; primary?: boolean };
export type Pack = { code: string; name: string; currency: string; languages: string[]; helplines: Helpline[] };
export type FilingPack = {
  ready: boolean;
  country: string;
  portal_name: string;
  portal_url: string;
  fields: { key: string; label: string; value: string; required: boolean; ok: boolean; hint?: string | null }[];
  narrative: string;
  narrative_ok: boolean;
  call_script: { q: string; a: string }[];
  bank_letter: string;
  restoration_request?: string | null;
  evidence_checklist: { file: string; ok: boolean | null; note?: string | null }[];
  missing: string[];
  disclaimer: string;
};
export type Precheck = { verdict: "likely_scam" | "suspicious" | "unclear"; scam_type: string; red_flags: string[]; advice: string };
export type QueueRow = {
  case_id: string;
  country: string;
  scam_type: string;
  total_lost: number;
  currency: string;
  score: number;
  minutes_since_txn: number | null;
  linked: number;
  stage: string;
  transactions: number;
  synthetic: boolean;
};
export type ScoreCard = {
  case_id: string;
  score: number;
  minutes_since_txn: number | null;
  factors: { name: string; value: string; weight: number; contribution: number }[];
  explanation?: string | null;
};
export type HoldRequest = { case_id: string; action: string; text: string; fields: Record<string, unknown> };

const memory = new Map<string, string>();
function readSession(key: string): string {
  try { return sessionStorage.getItem(key) ?? memory.get(key) ?? ""; }
  catch { return memory.get(key) ?? ""; }
}
function writeSession(key: string, value: string) {
  memory.set(key, value);
  try { sessionStorage.setItem(key, value); } catch { /* current tab memory fallback */ }
}
function reportCapabilities(): Record<string, string> {
  try {
    const saved = JSON.parse(readSession("gh-reports") || "{}");
    return saved && typeof saved === "object" && !Array.isArray(saved) ? saved : {};
  } catch { return {}; }
}
function rememberReport(id: string, secret: string) {
  const reports = reportCapabilities();
  reports[id] = secret;
  writeSession("gh-reports", JSON.stringify(Object.fromEntries(Object.entries(reports).slice(-50))));
}
async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (!(init?.body instanceof FormData)) headers.set("Content-Type", "application/json");
  if (path.startsWith("/console/")) headers.set("X-Case-Capabilities", JSON.stringify(reportCapabilities()));
  const caseId = path.match(/^\/cases\/([^/?]+)/)?.[1];
  if (caseId) headers.set("X-Case-Secret", readSession(`gh-case-${caseId}`));
  const r = await fetch(`${API_BASE}${path}`, { ...init, headers });
  if (!r.ok) {
    let msg = r.statusText;
    try {
      msg = (await r.json()).detail ?? msg;
    } catch {
      /* ignore */
    }
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return r.json() as Promise<T>;
}

export const api = {
  patterns: () => req<{ id: string; title: string; signs: string; action: string; source: string; url: string }[]>("/patterns"),
  packs: () => req<Pack[]>("/packs"),
  createCase: async (country: string, language: string) => {
    const result = await req<Case & { secret: string }>("/cases", { method: "POST", body: JSON.stringify({ country, language }) });
    writeSession(`gh-case-${result.id}`, result.secret);
    rememberReport(result.id, result.secret);
    const { secret, ...caseData } = result;
    return caseData as Case;
  },
  transferTime: (id: string, timestamp: string) => req<Case>(`/cases/${id}/transfer-time`, { method: "PUT", body: JSON.stringify({ timestamp }) }),
  getCase: (id: string) => req<Case>(`/cases/${id}`),
  language: (id: string, language: string) => req<Case>(`/cases/${id}/language`, { method: "PUT", body: JSON.stringify({ language }) }),
  upload: (id: string, files: File[], notes = "") => {
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f));
    fd.append("notes", notes);
    return req<{ case: Case; timeline: { time: string; event: string }[] }>(
      `/cases/${id}/evidence`,
      { method: "POST", body: fd },
    );
  },
  confirm: (id: string, transactions: Transaction[], suspects: Suspect[]) =>
    req<Case>(`/cases/${id}/confirm`, { method: "PUT", body: JSON.stringify({ transactions, suspects }) }),
  step: (id: string, step_id: string, done = true) =>
    req<Case>(`/cases/${id}/steps`, { method: "POST", body: JSON.stringify({ step_id, done }) }),
  ack: (id: string, ack_number: string) =>
    req<{ case: Case; reminders: { id: string; due_at: string; text: string }[] }>(`/cases/${id}/ack`, {
      method: "POST",
      body: JSON.stringify({ ack_number }),
    }),
  pack: (id: string) => req<FilingPack>(`/cases/${id}/pack`),
  restoration: (id: string) => req<{ restoration_request: string | null }>(`/cases/${id}/restoration`),
  reminders: (id: string) => req<{ id: string; due_at: string; text: string }[]>(`/cases/${id}/reminders`),
  share: (id: string) => req<{ token: string; expires_hours: number }>(`/cases/${id}/share`, { method: "POST" }),
  shared: (token: string) => req<Record<string, any>>(`/shared/${token}`),
  precheck: (text: string, country: string, language: string) =>
    req<Precheck>("/precheck", { method: "POST", body: JSON.stringify({ text, country, language }) }),
  recoveryCheck: (text: string, country: string, language: string) =>
    req<Precheck>("/recovery-check", { method: "POST", body: JSON.stringify({ text, country, language }) }),
  // console
  queue: (country?: string) => req<QueueRow[]>(`/console/queue${country ? `?country=${country}` : ""}`),
  consoleCase: (id: string) =>
    req<{ case: Case; score: ScoreCard; linked_cases: { case_id: string; shared: string[]; total_lost: number }[] }>(
      `/console/cases/${id}`,
    ),
  holdRequest: (id: string, body: { txn_id?: string }) =>
    req<HoldRequest>(`/console/cases/${id}/hold-request`, { method: "POST", body: JSON.stringify(body) }),
  clusters: () => req<{ case_ids: string[]; shared_identifiers: string[]; victims: number; total_lost: number; currency: string }[]>("/console/clusters"),
  attribution: (case_ids: string[], held_amount: number) =>
    req<{ case_id: string; loss: number; share: number; pct: number }[]>("/console/clusters/attribution", {
      method: "POST",
      body: JSON.stringify({ case_ids, held_amount }),
    }),
};

export function liveUrl(caseId: string, lang: string): string {
  const base = API_BASE.startsWith("http") ? API_BASE : `${location.origin}${API_BASE}`;
  return `${base.replace(/^http/, "ws")}/live/${caseId}?lang=${encodeURIComponent(lang)}&secret=${encodeURIComponent(readSession(`gh-case-${caseId}`))}`;
}
