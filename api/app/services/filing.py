"""FilingAgent: builds the country-specific ready-to-paste pack. Never submits anything."""
from __future__ import annotations

from datetime import datetime
import re

from app.config import get_settings
from app.llm import generate_text
from app.models import Case, FilingPack, Transaction
from app.packs import load_pack
from app.services.extract import transaction_fields
from app.tools.sanitize import pad_to_min, portal_ok, sanitize

SCAM_LABEL = {
    "investment": "fake investment scheme", "digital_arrest": "fake police / digital arrest call",
    "task_job": "fake online job / task scheme", "sextortion": "sextortion threat",
    "phishing_otp": "phishing / OTP fraud", "impersonation": "impersonation fraud",
    "shopping": "fake online shopping", "recovery_scam": "fake fund recovery offer",
    "unknown": "online financial fraud",
}


def reviewed_case(case: Case) -> Case:
    """Produce a draft-only copy without any invalid or unconfirmed payment value."""
    safe = case.model_copy(deep=True)
    safe.transactions = [t for t in safe.transactions if t.direction == "debit"]
    for t in safe.transactions:
        for _, obj, name in transaction_fields(t):
            field = getattr(obj, name)
            if not t.confirmed or not field.valid:
                field.value = None
                field.valid = False
    # These strings do not have source-check metadata; leave their portal boxes for manual review.
    safe.suspects, safe.timeline, safe.red_flags = [], [], []
    return safe


def _value(field, label: str) -> str:
    return field.value if field.valid and field.value else f"[please check: {label}]"


def _money(case: Case, amount: float) -> str:
    cur = load_pack(case.country)["currency"]
    return f"{cur} {amount:,.2f}"


def _fmt_time(iso: str | None) -> str:
    if not iso:
        return "time not known"
    try:
        return datetime.fromisoformat(iso).strftime("%d %b %Y, %I:%M %p")
    except ValueError:
        return iso


def _beneficiary(t: Transaction) -> str:
    b = t.beneficiary
    parts = [x.value for x in (b.vpa, b.account, b.ifsc, b.bank, b.name) if x.value and x.valid]
    return ", ".join(parts) or "[please check: beneficiary]"


def build_fields(case: Case) -> tuple[list[dict], list[str]]:
    case = reviewed_case(case)
    pack = load_pack(case.country)
    txns = case.transactions
    first = case.first_txn_time()
    values = {
        "category": pack.get("category"),
        "subcategory": pack["subcategory_map"].get(case.scam_type.value),
        "incident_datetime": first.strftime("%d-%m-%Y %H:%M") if first else None,
        "mode": ", ".join(sorted({t.rail.value for t in txns})) if txns else None,
        "victim_account": ", ".join(sorted({t.victim_account_masked.value for t in txns
                                            if t.victim_account_masked.value})) or None,
        "utr": "; ".join(t.utr.value for t in txns if t.utr.value) or None,
        "amount": "; ".join(_money(case, float(t.amount.value)) for t in txns if t.amount.value) or None,
        "txn_datetime": "; ".join(_fmt_time(t.timestamp.value) for t in txns if t.timestamp.value) or None,
        "suspect_account": "; ".join(dict.fromkeys(_beneficiary(t) for t in txns)) or None,
        "suspect_phone": "; ".join(s.phone for s in case.suspects if s.phone) or None,
        "suspect_url": "; ".join(x for s in case.suspects for x in (s.url, s.handle) if x) or None,
    }
    fields, missing = [], []
    bad_keys = set()
    if not txns:
        bad_keys.update(("utr", "amount", "txn_datetime", "suspect_account", "victim_account", "mode"))
    for t in txns:
        for key, good in (("utr", t.utr.valid), ("amount", t.amount.valid),
                          ("txn_datetime", t.timestamp.valid), ("incident_datetime", t.timestamp.valid),
                          ("victim_account", t.victim_account_masked.valid),
                          ("suspect_account", t.beneficiary.vpa.valid or t.beneficiary.account.valid)):
            if not good:
                bad_keys.add(key)
    for f in pack["fields"]:
        v = values.get(f["key"])
        ok = bool(v)
        hint = None
        if f["key"] in bad_keys:
            ok, hint = False, "Review, correct and confirm every transfer before copying this field."
        if f["key"] == "victim_account" and not v:
            hint = "Last 4 digits of your account or card."
        if not ok:
            missing.append(f["label"])
        fields.append({"key": f["key"], "label": f["label"], "value": v if ok else f"[please check: {f['label']}]",
                       "required": f.get("required", False), "ok": ok, "hint": hint})
    return fields, missing


def build_narrative(case: Case, timeline: list[dict] | None = None) -> tuple[str, bool]:
    unsafe_values = {field.value.casefold() for t in case.transactions
                     for _, obj, name in transaction_fields(t)
                     if (field := getattr(obj, name)).value and (not field.valid or not t.confirmed)}
    case = reviewed_case(case)
    s = get_settings()
    portal = load_pack(case.country)["portal"]
    forbidden = portal.get("narrative_forbidden_chars", "")
    min_chars = int(portal.get("narrative_min_chars", 0))
    facts = {
        "scam_type": case.scam_type.value, "red_flags": case.red_flags,
        # Extracted timeline text has no review/grounding status. It cannot supply report facts.
        "timeline": [],
        "transactions": [{"amount": t.amount.value, "time": t.timestamp.value, "utr": t.utr.value,
                          "to": _beneficiary(t), "rail": t.rail.value} for t in case.transactions],
        "suspects": [x.model_dump(exclude_none=True) for x in case.suspects],
    }
    try:
        text = generate_text(
            model=s.model_main,
            system=("Write the incident description for a police cyber-fraud complaint in plain "
                    "English, first person, past tense, chronological, factual, 120-250 words. "
                    "Include every transaction with amount, time and reference. Do not use any "
                    "of these characters: " + (forbidden or "none") + ". No headings, no lists."),
            prompt=str(facts),
        )
    except Exception:  # noqa: BLE001 - template fallback keeps the flow working offline
        text = ""
    # Reject invented numeric identifiers/amounts and require every checked transaction fact.
    required = [field.value for t in case.transactions for _, obj, name in transaction_fields(t)
                if (field := getattr(obj, name)).valid and field.value and name in ("utr", "amount")]
    allowed_numbers = set(re.findall(r"\d+", str(facts)))
    allowed_vpas = {t.beneficiary.vpa.value.casefold() for t in case.transactions
                    if t.beneficiary.vpa.valid and t.beneficiary.vpa.value}
    mentioned_vpas = {v.casefold() for v in re.findall(r"[\w.-]+@[\w.-]+", text)}
    if (not text or any(value not in text.replace(",", "") for value in required) or
            any(value in text.casefold() for value in unsafe_values) or
            not mentioned_vpas.issubset(allowed_vpas) or
            not set(re.findall(r"\d+", text)).issubset(allowed_numbers)):
        lines = [f"I was cheated in a {SCAM_LABEL[case.scam_type.value]}."]
        for t in case.transactions:
            lines.append(f"On {_fmt_time(t.timestamp.value)} I transferred {_value(t.amount, 'amount')} "
                         f"via {t.rail.value} with reference {_value(t.utr, 'reference')} to "
                         f"{_beneficiary(t)}.")
        text = " ".join(lines)
    # NCRP forbids '@': keep UPI IDs readable ("abc.trade at okaxis") instead of mangling them.
    if "@" in forbidden:
        text = text.replace("@", " at ")
    text = sanitize(text, forbidden)
    text = pad_to_min(text, min_chars, "I request that the money be traced and held and the "
                      "fraudsters be identified. I will provide the reviewed payment evidence with my complaint.")
    return text, portal_ok(text, forbidden, min_chars)


def build_call_script(case: Case) -> list[dict]:
    case = reviewed_case(case)
    pack = load_pack(case.country)
    first = case.first_txn_time()
    ctx = {
        "scam_label": SCAM_LABEL[case.scam_type.value],
        "first_time": first.strftime("%I:%M %p, %d %b") if first else "not sure",
        "total": _money(case, case.total_lost()) if case.transactions and all(t.amount.valid for t in case.transactions) else "[please check: total amount]",
        "utr_list": "; ".join(f"{t.utr.value} ({t.amount.value})" for t in case.transactions
                              if t.utr.value and t.amount.valid) or "[please check: references and amounts]",
        "victim_accounts": ", ".join(sorted({t.victim_account_masked.value for t in case.transactions
                                             if t.victim_account_masked.value})) or "my bank account",
        "beneficiaries": "; ".join(dict.fromkeys(_beneficiary(t) for t in case.transactions)) or "not known",
        "suspects": "; ".join(x for s in case.suspects for x in (s.phone, s.url, s.handle) if x)
                    or "not known",
    }
    primary = next(h for h in pack["helplines"] if h.get("primary"))
    guidance = {"q": f"Call {primary['number']} now", "a": "Do not wait for a complete report to contact the helpline and your bank."}
    if case.country == "MY":
        guidance["a"] += " After contacting your bank or NSRC 997, file a separate police report at the nearest police station within 24 hours."
    if pack.get("step_order", [""])[0] == "bank_block":
        guidance = {"q": "Call your bank first", "a": "Use your bank’s 24/7 anti-scam hotline or kill switch, then call ScamShield 1799 and lodge a police report."}
    if case.language == "hi" and case.country == "IN":
        guidance = {"q": "अभी 1930 पर कॉल करें", "a": "पूरी रिपोर्ट का इंतज़ार न करें। तुरंत हेल्पलाइन और बैंक से संपर्क करें।"}
        ctx["scam_label"] = "ऑनलाइन आर्थिक धोखाधड़ी"
        fallback_labels = {"not sure": "समय की पुष्टि बाकी है", "not known": "जानकारी उपलब्ध नहीं है",
                           "my bank account": "मेरा बैंक खाता", "[please check: total amount]": "[कुल राशि जाँचें]",
                           "[please check: references and amounts]": "[ट्रांजैक्शन संदर्भ और राशि जाँचें]"}
        ctx = {key: fallback_labels.get(value, value) for key, value in ctx.items()}
    scripts = pack.get("call_script_hi", pack["call_script"]) if case.language == "hi" else pack["call_script"]
    return [guidance] + [{"q": item["q"], "a": item["a_template"].format(**ctx)} for item in scripts]


def build_bank_letter(case: Case) -> str:
    case = reviewed_case(case)
    rows = "\n".join(
        f"  {i}. {_fmt_time(t.timestamp.value)} | {t.rail.value} | Ref {_value(t.utr, 'reference')} | "
        f"{_money(case, float(t.amount.value)) if t.amount.valid and t.amount.value else '[please check: amount]'} | To: {_beneficiary(t)}"
        for i, t in enumerate(case.transactions, 1))
    ack = f"Cyber-crime acknowledgement / reference: {case.ack_number}\n" if case.ack_number else ""
    return (
        "To: The Branch Manager / Fraud Desk\n\n"
        "Subject: Urgent - report of fraudulent transactions and request to block and recover funds\n\n"
        "Dear Sir/Madam,\n\n"
        f"I am reporting that I was victim of a {SCAM_LABEL[case.scam_type.value]}. "
        "The following transactions were made from my account under deception:\n\n"
        f"{rows}\n\n{ack}"
        "I request you to (1) immediately block further debits on my account, cards and UPI, "
        "(2) raise a request with the beneficiary bank(s) to hold the disputed amounts, and "
        "(3) share the status and any reference number for this dispute.\n\n"
        "I will attach the reviewed payment evidence when I send this letter.\n\n"
        "Yours faithfully,\n[Name]\n[Registered mobile]\n[Date]"
    )


def build_restoration(case: Case) -> str | None:
    case = reviewed_case(case)
    pack = load_pack(case.country)
    if not pack.get("restoration", {}).get("enabled"):
        return None
    total = _money(case, case.total_lost())
    return (
        "Request for restoration of held amount\n\n"
        f"Complaint / acknowledgement number: {case.ncrp_complaint_id or case.ack_number or '[enter]'}\n"
        f"Total amount lost: {total}\n"
        "Transactions:\n" + "\n".join(
            f"  - Ref {_value(t.utr, 'reference')}: {_value(t.amount, 'amount')} on {_fmt_time(t.timestamp.value)}"
            for t in case.transactions) +
        "\n\nI request that any amount held in the beneficiary account(s) linked to this complaint "
        "be restored to my account. I am willing to submit an indemnity bond if required.\n"
    )


def evidence_checklist(case: Case) -> list[dict]:
    portal = load_pack(case.country)["portal"]
    limit = portal["evidence_max_mb"] * 1024 * 1024
    items = [{"file": e.filename, "ok": e.size_bytes <= limit,
              "note": None if e.size_bytes <= limit else f"Over {portal['evidence_max_mb']} MB - compress it"}
             for e in case.evidence]
    wanted = ["Bank debit SMS or statement showing each transfer",
              "Screenshot of the chat / call log with the fraudster",
              "Screenshot of the fake app, website or profile"]
    # Suggestions only help when little evidence is attached.
    return items + ([] if len(case.evidence) >= 2 else [{"file": w, "ok": None, "note": "Suggested"} for w in wanted])


def build_pack(case: Case, timeline: list[dict] | None = None) -> FilingPack:
    pack = load_pack(case.country)
    fields, missing = build_fields(case)
    narrative, narrative_ok = build_narrative(case, timeline)
    ready = bool(case.transactions) and all(t.confirmed for t in case.transactions) and all(f["ok"] for f in fields if f["required"])
    if not all(t.confirmed for t in case.transactions):
        missing.append("Confirm every transaction")
    return FilingPack(
        ready=ready,
        country=case.country, portal_name=pack["portal"]["name"], portal_url=pack["portal"]["url"],
        fields=fields, narrative=narrative, narrative_ok=narrative_ok,
        call_script=build_call_script(case), bank_letter=build_bank_letter(case),
        restoration_request=build_restoration(case), evidence_checklist=evidence_checklist(case),
        missing=missing, disclaimer=pack["disclaimer"],
    )
