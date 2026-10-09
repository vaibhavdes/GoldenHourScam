"""EvidenceExtractor: multimodal Gemini -> grounded transactions, suspects, timeline."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from decimal import Decimal, InvalidOperation

from app.config import get_settings
from app.llm import client, file_part, generate_json, transcribe
from app.models import Beneficiary, Case, Field_, Rail, Suspect, Transaction
from app.tools.validators import validate_case, validate_transaction

_FIELD = {
    "type": "OBJECT",
    "properties": {
        "value": {"type": "STRING", "nullable": True},
        "confidence": {"type": "NUMBER"},
        "source_quote": {"type": "STRING", "nullable": True},
        "source_file": {"type": "STRING", "nullable": True},
    },
    "required": ["confidence"],
}

SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "transactions": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "direction": {"type": "STRING", "enum": ["debit", "credit"]},
                    "rail": {"type": "STRING", "enum": [r.value for r in Rail]},
                    "currency": {"type": "STRING"},
                    "amount": _FIELD,
                    "utr": _FIELD,
                    "timestamp": _FIELD,
                    "victim_account_masked": _FIELD,
                    "beneficiary_vpa": _FIELD,
                    "beneficiary_account": _FIELD,
                    "beneficiary_ifsc": _FIELD,
                    "beneficiary_bank": _FIELD,
                    "beneficiary_name": _FIELD,
                    "is_fraud_related": {"type": "BOOLEAN"},
                },
                "required": ["direction", "rail", "amount", "utr", "timestamp", "is_fraud_related"],
            },
        },
        "suspects": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "phone": {"type": "STRING", "nullable": True},
                    "url": {"type": "STRING", "nullable": True},
                    "handle": {"type": "STRING", "nullable": True},
                    "platform": {"type": "STRING", "nullable": True},
                    "claimed_identity": {"type": "STRING", "nullable": True},
                },
            },
        },
        "timeline": {
            "type": "ARRAY",
            "items": {"type": "OBJECT", "properties": {
                "time": {"type": "STRING"}, "event": {"type": "STRING"}}},
        },
    },
    "required": ["transactions", "suspects", "timeline"],
}

SYSTEM = """You extract payment evidence for a scam victim's police/bank report.
Input: one or more files (bank SMS screenshots, UPI/payment receipts, bank statements, chat exports).

Rules:
- Extract EVERY money transfer you can see. Mark is_fraud_related=false for clearly unrelated
  everyday payments (groceries, salary) and refunds/credits that are not to the scammer.
- For every value give `source_quote`: the exact characters copied from the file that contain
  the value, and `source_file`: the file label given before each file. If you cannot see a value,
  return value=null. NEVER guess or construct an ID.
- amount: digits with optional 2 decimals, no currency symbol or commas (e.g. "49999.00").
- timestamp: ISO 8601 local time with the given timezone offset, e.g. 2026-10-03T10:31:00+05:30.
  If the year is missing assume {year}.
- UTR/RRN/reference: UPI and IMPS references in India are exactly 12 digits.
  TRAPS - these are NOT the reference: helpline numbers (1800..., 1930), OTPs, customer care
  numbers, available balance, masked account numbers (XX1234), complaint numbers.
  Malaysia DuitNow / IBG references are long alphanumeric strings (e.g. 20261003MBBE010ORB12345678).
- Ignore OTP messages, balance alerts and small everyday payments to shops/utilities unless the
  user's notes say they were part of the scam (set is_fraud_related=false for them).
- victim_account_masked: the victim's own account as shown (e.g. XX4821).
- beneficiary_*: where the money went (UPI ID like name@bank, account number, IFSC, bank, name).
- suspects: phone numbers, links, app names, social handles used by the fraudster, and who they
  claimed to be (e.g. "CBI officer", "stock advisor").
- timeline: short chronological events (call received, app installed, transfers, threats).
- confidence: 0-1, how sure you are the value is read correctly.
Country: {country}. Default currency: {currency}. Timezone offset: {tz}.
"""

TZ = {"IN": "+05:30", "MY": "+08:00", "SG": "+08:00", "ID": "+07:00"}
CUR = {"IN": "INR", "MY": "MYR", "SG": "SGD", "ID": "IDR"}


def _f(d: dict | None) -> Field_:
    d = d or {}
    v = d.get("value")
    return Field_(value=str(v) if v not in (None, "") else None,
                  confidence=float(d.get("confidence") or 0),
                  source_quote=d.get("source_quote"), source_file=d.get("source_file"))


FIELD_PATHS = ("amount", "utr", "timestamp", "victim_account_masked",
               "beneficiary.vpa", "beneficiary.account", "beneficiary.ifsc",
               "beneficiary.bank", "beneficiary.name")


def transaction_fields(t: Transaction):
    for path in FIELD_PATHS:
        obj = t.beneficiary if path.startswith("beneficiary.") else t
        yield path, obj, path.split(".")[-1]


def _equivalent(a: str, b: str, path: str) -> bool:
    if path == "amount":
        try:
            return Decimal(a) == Decimal(b)
        except InvalidOperation:
            return False
    if path == "timestamp":
        try:
            return datetime.fromisoformat(a) == datetime.fromisoformat(b)
        except ValueError:
            return False
    return a.strip().casefold() == b.strip().casefold()


def _same_transfer(a: Transaction, b: Transaction) -> bool:
    if a.utr.value and b.utr.value:
        return _equivalent(a.utr.value, b.utr.value, "utr")
    # Without an ID, use all three independent clues; an ambiguous match is not merged.
    if a.direction != b.direction or a.currency != b.currency:
        return False
    if not a.amount.value or not b.amount.value or not _equivalent(a.amount.value, b.amount.value, "amount"):
        return False
    same_beneficiary = any(x.value and y.value and _equivalent(x.value, y.value, "beneficiary")
                           for x, y in ((a.beneficiary.vpa, b.beneficiary.vpa),
                                        (a.beneficiary.account, b.beneficiary.account)))
    if not same_beneficiary or not a.timestamp.value or not b.timestamp.value:
        return False
    try:
        return abs((datetime.fromisoformat(a.timestamp.value) -
                    datetime.fromisoformat(b.timestamp.value)).total_seconds()) <= 120
    except (ValueError, TypeError):
        return False


def merge_transactions(case: Case, incoming: list[Transaction]) -> None:
    for new in incoming:
        validate_transaction(new, case.country, case.evidence_text)
        matches = [old for old in case.transactions if _same_transfer(old, new)]
        if len(matches) != 1:
            case.transactions.append(new)
            continue
        old = matches[0]
        for path, obj, name in transaction_fields(old):
            current = getattr(obj, name)
            other_obj = new.beneficiary if path.startswith("beneficiary.") else new
            other = getattr(other_obj, name)
            if current.value and other.value and not _equivalent(current.value, other.value, path):
                winner = (other if other.confidence > current.confidence else current).model_copy(deep=True)
                winner.valid = False
                winner.issue = f"Conflicting values in your screenshots: {current.value} vs {other.value}"
                setattr(obj, name, winner)
                old.confirmed = False
            elif (other.value and not (current.issue or "").startswith("Conflicting values in your screenshots:")
                  and (not current.value or (not current.valid and other.valid))):
                setattr(obj, name, other.model_copy(deep=True))
                old.confirmed = False
        if old.rail == Rail.UNKNOWN and new.rail != Rail.UNKNOWN:
            old.rail = new.rail
            old.confirmed = False
        validate_transaction(old, case.country, case.evidence_text)


def extract(case: Case, files: list[tuple[str, str, bytes]]) -> tuple[Case, list[dict]]:
    """files: [(label, mime, bytes)] -> updated case + timeline."""
    s = get_settings()
    system = SYSTEM.format(country=case.country, currency=CUR.get(case.country, "INR"),
                           tz=TZ.get(case.country, "+00:00"), year=case.created_at.year)
    parts: list = []
    for label, mime, data in files:
        parts.append(f"FILE {label}:")
        parts.append(file_part(data, mime))
    parts.append("Extract now.")

    # Independent transcriptions never see extractor output, so they can run concurrently with
    # the main extraction call. This cuts N+1 sequential model calls to roughly one round trip.
    client()  # warm the shared client before threads (avoid concurrent cold initialisation)
    binaries = [(label, mime, data) for label, mime, data in files if not mime.startswith("text/")]
    for label, mime, data in files:
        if mime.startswith("text/"):
            case.evidence_text[label] = data.decode("utf-8", errors="replace")
    with ThreadPoolExecutor(max_workers=min(8, len(binaries) + 1)) as pool:
        main_future = pool.submit(generate_json, model=s.model_main, system=system, parts=parts, schema=SCHEMA)
        text_futures = {label: pool.submit(transcribe, model=s.model_lite, data=data, mime=mime)
                        for label, mime, data in binaries}
        raw = main_future.result()
        for label, fut in text_futures.items():
            case.evidence_text[label] = fut.result()

    txns = []
    for t in raw.get("transactions", []):
        if not t.get("is_fraud_related", True):
            continue
        try:
            rail = Rail(t.get("rail", "UNKNOWN"))
        except ValueError:
            rail = Rail.UNKNOWN
        txns.append(Transaction(
            amount=_f(t.get("amount")), currency=t.get("currency") or CUR.get(case.country, "INR"),
            rail=rail, utr=_f(t.get("utr")), timestamp=_f(t.get("timestamp")),
            victim_account_masked=_f(t.get("victim_account_masked")),
            direction=t.get("direction", "debit"),
            beneficiary=Beneficiary(
                vpa=_f(t.get("beneficiary_vpa")), account=_f(t.get("beneficiary_account")),
                ifsc=_f(t.get("beneficiary_ifsc")), bank=_f(t.get("beneficiary_bank")),
                name=_f(t.get("beneficiary_name"))),
        ))

    merge_transactions(case, txns)

    for sp in raw.get("suspects", []):
        sus = Suspect(**{k: sp.get(k) for k in Suspect.model_fields})
        if any(getattr(sus, k) for k in Suspect.model_fields) and sus not in case.suspects:
            case.suspects.append(sus)

    validate_case(case)
    return case, raw.get("timeline", [])
