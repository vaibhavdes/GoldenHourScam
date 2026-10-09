"""ScamClassifier + pre-payment 'Am I being scammed?' check."""
from __future__ import annotations
import logging

from app.config import get_settings
from app.llm import generate_json
from app.models import Case, PrecheckResp, ScamType
from app.packs import load_pack

LANG = {"en": "English", "hi": "Hindi", "ms": "Bahasa Melayu", "id": "Bahasa Indonesia"}

TYPOLOGY = """Scam types:
- investment: fake stock/crypto/IPO trading apps or WhatsApp/Telegram 'advisor' groups, fake profits, withdrawal fees.
- digital_arrest: caller poses as police/CBI/customs/RBI/court; parcel with drugs, money laundering case; video call 'arrest'; asks to move money to a 'safe/verification' account. (No 'digital arrest' exists in law.)
- task_job: paid likes/reviews/tasks, 'prepaid tasks' to unlock earnings, part-time job offers.
- sextortion: intimate video call recorded, threats to share unless paid.
- phishing_otp: fake KYC/bank/electricity messages, OTP sharing, screen-sharing apps, APK installs, SIM swap.
- impersonation: fake relative/boss/friend in trouble, fake customer care.
- shopping: fake online sellers, undelivered goods, fake booking sites.
- recovery_scam: someone offers to recover lost money for a fee / 'hacker' / fake lawyer.
"""

CLASSIFY_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "scam_type": {"type": "STRING", "enum": [s.value for s in ScamType]},
        "confidence": {"type": "NUMBER"},
        "red_flags": {"type": "ARRAY", "items": {"type": "STRING"}},
        "explanation": {"type": "STRING"},
    },
    "required": ["scam_type", "confidence", "red_flags", "explanation"],
}


def classify(case: Case, timeline: list[dict], extra_text: str = "") -> Case:
    s = get_settings()
    lang = LANG.get(case.language, "English")
    facts = {
        "timeline": timeline,
        "suspects": [x.model_dump() for x in case.suspects],
        "transactions": [{"amount": t.amount.value, "rail": t.rail.value,
                          "beneficiary": t.beneficiary.vpa.value or t.beneficiary.account.value}
                         for t in case.transactions],
        "victim_notes": extra_text,
    }
    try:
        out = _classification(s.model_main, lang, facts)
    except Exception as error:
        logging.getLogger(__name__).warning("Scam classification unavailable: %s", type(error).__name__)
        primary = next(h for h in load_pack(case.country)["helplines"] if h.get("primary"))
        case.explanation = ("AI विश्लेषण अभी उपलब्ध नहीं है। भुगतान की जानकारी जाँचें और तुरंत 1930 तथा बैंक से संपर्क करें।" if case.language == "hi" and case.country == "IN" else "AI analysis is unavailable right now. Review the payment details and contact your bank immediately." + (f" Call {primary['number']}." if case.country != "SG" else " Then call 1799 and lodge a police report."))
        return case
    try:
        case.scam_type = ScamType(out.get("scam_type", "unknown"))
    except ValueError:
        case.scam_type = ScamType.UNKNOWN
    case.scam_type_confidence = float(out.get("confidence") or 0)
    case.red_flags = out.get("red_flags", [])[:5]
    case.explanation = out.get("explanation")
    return case


def _classification(model: str, lang: str, facts: dict) -> dict:
    return generate_json(
        model=model,
        system=(f"{TYPOLOGY}\nClassify the scam. red_flags: 2-5 short, concrete signs from the facts in {lang}. "
                f"explanation: 2-3 calm, simple sentences in {lang} for an older person, telling them "
                "this was a scam, it is not their fault, and the most important next step."),
        parts=[str(facts)],
        schema=CLASSIFY_SCHEMA,
        timeout_ms=45_000,  # shown prominently to the victim; allow for long multi-file timelines
    )


PRECHECK_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "verdict": {"type": "STRING", "enum": ["likely_scam", "suspicious", "unclear"]},
        "scam_type": {"type": "STRING", "enum": [s.value for s in ScamType]},
        "red_flags": {"type": "ARRAY", "items": {"type": "STRING"}},
        "advice": {"type": "STRING"},
    },
    "required": ["verdict", "scam_type", "red_flags", "advice"],
}


def precheck(text: str, country: str, language: str) -> PrecheckResp:
    s = get_settings()
    lang = LANG.get(language, "English")
    out = generate_json(
        model=s.model_lite,
        system=(f"{TYPOLOGY}\nA person describes a call/message they are getting RIGHT NOW, "
                f"possibly before paying. Country: {country}. Decide if it is likely a scam. "
                f"advice: 1-3 short imperative sentences in {lang}. If likely_scam: tell them to stop, "
                "hang up, not pay, and verify via an official number they already know. "
                "If it is a 'recovery' offer that asks for fees, it is a scam. Never tell them to pay."),
        parts=[text],
        schema=PRECHECK_SCHEMA,
        timeout_ms=30_000,
    )
    try:
        st = ScamType(out.get("scam_type", "unknown"))
    except ValueError:
        st = ScamType.UNKNOWN
    return PrecheckResp(verdict=out.get("verdict", "unclear"), scam_type=st,
                        red_flags=out.get("red_flags", [])[:5], advice=out.get("advice", ""))
