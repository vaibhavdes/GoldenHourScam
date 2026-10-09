import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { api, type Pack } from "./api";
import type { Lang } from "./i18n";

type Ctx = {
  country: string;
  setCountry: (c: string) => void;
  lang: Lang;
  setLang: (l: Lang) => void;
  packs: Pack[];
  pack?: Pack;
  bigText: boolean;
  setBigText: (b: boolean) => void;
};

const AppCtx = createContext<Ctx | null>(null);

function read(key: string, fallback: string): string {
  try {
    return localStorage.getItem(key) ?? fallback;
  } catch {
    return fallback;
  }
}
function write(key: string, v: string) {
  try {
    localStorage.setItem(key, v);
  } catch {
    /* storage may be unavailable */
  }
}

export const FALLBACK_PACKS: Pack[] = [
  { code: "IN", name: "India", currency: "INR", languages: ["en", "hi"], helplines: [
    { id: "national", label: "National Cyber Crime Helpline", number: "1930", primary: true },
    { id: "police", label: "Police emergency", number: "112" }] },
  { code: "MY", name: "Malaysia", currency: "MYR", languages: ["en", "ms"], helplines: [
    { id: "national", label: "National Scam Response Centre", number: "997", primary: true },
    { id: "police", label: "Police emergency", number: "999" }] },
  { code: "SG", name: "Singapore", currency: "SGD", languages: ["en"], helplines: [
    { id: "national", label: "ScamShield — call your bank first", number: "1799", primary: true },
    { id: "police", label: "Police emergency", number: "999" }] },
];

/** Best guess of country from the device's time zone and language. Private: nothing leaves the device. */
export function detectCountry(): string {
  try {
    const tz = Intl.DateTimeFormat().resolvedOptions().timeZone || "";
    if (/Kolkata|Calcutta/.test(tz)) return "IN";
    if (/Kuala_Lumpur|Kuching/.test(tz)) return "MY";
    if (/Singapore/.test(tz)) return "SG";
    const langs = (navigator.languages || [navigator.language]).join(",");
    if (/-IN\b/.test(langs) || /\bhi\b/.test(langs)) return "IN";
    if (/-MY\b/.test(langs) || /\bms\b/.test(langs)) return "MY";
    if (/-SG\b/.test(langs)) return "SG";
  } catch { /* fall through */ }
  return "IN";
}

export function detectLang(): Lang {
  try {
    const first = (navigator.languages?.[0] || navigator.language || "en").toLowerCase();
    if (first.startsWith("hi")) return "hi";
    if (first.startsWith("ms")) return "ms";
  } catch { /* fall through */ }
  return "en";
}

export function AppProvider({ children }: { children: ReactNode }) {
  const [country, setCountryS] = useState(() => { const saved = read("gh.country", ""); return FALLBACK_PACKS.some(p => p.code === saved) ? saved : detectCountry(); });
  const [lang, setLangS] = useState<Lang>(() => { const saved = read("gh.lang", ""); return ["en", "hi", "ms"].includes(saved) ? saved as Lang : detectLang(); });
  const [bigText, setBigTextS] = useState(read("gh.big", "0") === "1");
  const [packs, setPacks] = useState<Pack[]>(FALLBACK_PACKS);

  useEffect(() => {
    api.packs().then((loaded) => setPacks(loaded.length ? loaded : FALLBACK_PACKS)).catch(() => setPacks(FALLBACK_PACKS));
  }, []);
  useEffect(() => { document.documentElement.lang = lang; }, [lang]);
  useEffect(() => {
    document.documentElement.dataset.big = bigText ? "1" : "0";
  }, [bigText]);

  const value: Ctx = {
    country,
    setCountry: (c) => (setCountryS(c), write("gh.country", c)),
    lang,
    setLang: (l) => (setLangS(l), write("gh.lang", l)),
    packs,
    pack: packs.find((p) => p.code === country),
    bigText,
    setBigText: (b) => (setBigTextS(b), write("gh.big", b ? "1" : "0")),
  };
  return <AppCtx.Provider value={value}>{children}</AppCtx.Provider>;
}

export function useApp(): Ctx {
  const c = useContext(AppCtx);
  if (!c) throw new Error("useApp outside provider");
  return c;
}

export function fmtMoney(amount: number, currency: string): string {
  try {
    return new Intl.NumberFormat(currency === "INR" ? "en-IN" : "en", { style: "currency", currency }).format(amount);
  } catch {
    return `${currency} ${amount.toFixed(2)}`;
  }
}

export function minutesSince(iso?: string | null): number | null {
  if (!iso) return null;
  const t = new Date(iso).getTime();
  return Number.isNaN(t) ? null : (Date.now() - t) / 60000;
}
