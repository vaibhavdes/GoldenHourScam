"""Small, explicitly fictional judging scenarios; no real victim records or OCR claims."""
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException
from app.models import Beneficiary, Case, Field_, Rail, ScamType, Stage, Transaction, now
from app.services.lockdown import ensure_steps
from app.tools.validators import validate_case

SCENARIOS = [
    {"id": "digital-arrest", "title": "Fake police call", "country": "IN", "type": "digital_arrest", "amounts": [75000, 120000], "minutes": 22, "age": 64, "notes": "A fake police officer on a video call demanded two transfers to a 'safe account'. The caller threatened arrest and told the person not to tell family.", "covers": "Two transfers · older person · linked recipient"},
    {"id": "investment", "title": "Investment withdrawal fee", "country": "IN", "type": "investment", "amounts": [85000], "minutes": 38, "notes": "A WhatsApp investment group showed invented profits, then demanded another tax payment before allowing withdrawal.", "covers": "Investment scam · shared recipient"},
    {"id": "task-job", "title": "Prepaid online tasks", "country": "IN", "type": "task_job", "amounts": [12000, 28000], "minutes": 52, "notes": "A Telegram recruiter paid for likes, then required increasingly large prepaid tasks to unlock the balance.", "covers": "Multiple payments · shared recipient"},
    {"id": "phishing", "title": "KYC link and stolen OTP", "country": "IN", "type": "phishing_otp", "amounts": [24000], "minutes": 14, "notes": "A fake KYC message sent the person to a lookalike banking page. After an OTP was entered, an unauthorized transfer appeared.", "covers": "Unauthorized payment · account lockdown"},
    {"id": "impersonation", "title": "A relative asks for urgent help", "country": "IN", "type": "impersonation", "amounts": [18000], "minutes": 90, "notes": "A new number pretended to be a relative needing an emergency payment. The real relative later confirmed they had not asked for money.", "covers": "Impersonation · outside the first hour"},
    {"id": "shopping", "title": "Marketplace seller disappears", "country": "IN", "type": "shopping", "amounts": [6500], "minutes": 210, "notes": "A marketplace seller took payment for a phone and then blocked the buyer. No item was shipped.", "covers": "Shopping fraud · lower loss · delayed report"},
    {"id": "sextortion", "title": "Threats after a video call", "country": "IN", "type": "sextortion", "amounts": [15000], "minutes": 33, "notes": "A stranger threatened to share a fabricated private video unless paid. A payment was made, and further demands followed. No explicit media is included.", "covers": "Sensitive scenario · evidence preservation"},
    {"id": "recovery-fee", "title": "A second scam offers recovery", "country": "IN", "type": "recovery_scam", "amounts": [4999], "minutes": 17, "notes": "An unsolicited recovery agent asked for an advance fee to get earlier stolen money back, then asked for another processing charge.", "covers": "Recovery scam · stop further payments"},
    {"id": "masked-account", "title": "Receipt hides the recipient", "country": "IN", "type": "impersonation", "amounts": [31000], "minutes": 26, "notes": "An IMPS message only shows recipient account XX7864. The full destination account is unavailable; do not guess it or delay calling the bank.", "covers": "Masked account · blocked draft · manual correction"},
    {"id": "incoming-credit", "title": "A debit beside an incoming credit", "country": "IN", "type": "shopping", "amounts": [9000], "minutes": 44, "notes": "An online seller disappeared after payment. The same statement contains an unrelated incoming salary credit, which must not be counted as scam loss.", "covers": "Statement noise · incoming credit excluded"},
    {"id": "malaysia", "title": "DuitNow investment transfer", "country": "MY", "type": "investment", "amounts": [30100], "minutes": 19, "notes": "A fake investment adviser requested a DuitNow transfer, then demanded a withdrawal charge. Contact the bank/997, then make a separate police report.", "covers": "RM currency · DuitNow · separate police report"},
    {"id": "singapore", "title": "Fake seller requests PayNow", "country": "SG", "type": "shopping", "amounts": [1200], "minutes": 12, "notes": "A fake ticket seller asked for PayNow payment and disappeared. Contact the bank first, then ScamShield and make the police report.", "covers": "SGD currency · PayNow · bank-first order"},
]


def _scenario(example_id: str) -> tuple[int, dict]:
    for index, item in enumerate(SCENARIOS):
        if item["id"] == example_id:
            return index, item
    raise HTTPException(404, "Example not found")


def catalog() -> list[dict]:
    return [{k: s[k] for k in ("id", "title", "country", "type", "covers", "notes")} for s in SCENARIOS]


def entered(value) -> Field_:
    return Field_(value=str(value) if value is not None else None, status="user" if value is not None else "missing", source_file="Prepared fictional example", confidence=1 if value is not None else 0)


def make_example(example_id: str, *, fresh: bool = False) -> Case:
    index, s = _scenario(example_id)
    country = s["country"]
    currency = {"IN": "INR", "MY": "MYR", "SG": "SGD"}[country]
    offset = timezone(timedelta(hours=5, minutes=30)) if country == "IN" else timezone(timedelta(hours=8))
    args = {} if fresh else {"id": "GH-EX-" + example_id.upper()}
    case = Case(**args, country=country, language="en", synthetic=True, victim_name="Sample person (fictional)", victim_age=s.get("age", 38), scam_type=ScamType(s["type"]), scam_type_confidence=0,
                explanation="Fictional scenario: " + s["notes"], stage=Stage.SOS if fresh else Stage.FILING)
    rail = Rail.UPI if country == "IN" else Rail.DUITNOW if country == "MY" else Rail.PAYNOW
    if example_id == "masked-account":
        rail = Rail.IMPS
    shared = index < 3
    for n, amount in enumerate(s["amounts"]):
        timestamp = (now() - timedelta(minutes=s["minutes"] - n * 3)).astimezone(offset).replace(second=0, microsecond=0).isoformat()
        reference = f"{830000000000 + index * 100 + n}" if country == "IN" else f"EX20261008{'MY' if country == 'MY' else 'SG'}{index:04}{n:04}"
        beneficiary = Beneficiary(vpa=entered("fictional.mule01@samplebank" if shared else f"fictional.payee{index:02}@samplebank")) if rail == Rail.UPI else Beneficiary(account=entered("XX7864" if rail == Rail.IMPS else f"76543210{index:04}"))
        case.transactions.append(Transaction(rail=rail, currency=currency, amount=entered(amount), utr=entered(reference), timestamp=entered(timestamp), victim_account_masked=entered("XX4821"), beneficiary=beneficiary, confirmed=not fresh))
    if example_id == "incoming-credit":
        credit = case.transactions[0].model_copy(deep=True)
        credit.id += "-credit"; credit.direction = "credit"; credit.amount = entered(36000); credit.utr = entered("830000009999")
        credit.beneficiary = Beneficiary(vpa=entered("fictional.employer@samplebank"))
        case.transactions.append(credit)
    validate_case(case)
    ensure_steps(case)
    return case


def receipt(example_id: str) -> str:
    case = make_example(example_id, fresh=True)
    _, s = _scenario(example_id)
    lines = ["FICTIONAL SAMPLE ONLY — not a real bank document.", "Prepared for GoldenHour hackathon evaluation.", ""]
    for t in case.transactions:
        to = t.beneficiary.vpa.value or t.beneficiary.account.value
        local = datetime.fromisoformat(t.timestamp.value)
        label = "Beneficiary UPI ID" if t.rail == Rail.UPI else "Beneficiary account"
        lines.extend([f"{t.rail.value} {'outgoing payment' if t.direction == 'debit' else 'incoming salary credit (unrelated to fraud)'}", f"Amount: {t.currency} {float(t.amount.value):,.2f}", f"Transaction reference: {t.utr.value}", f"Date/time: {local.strftime('%d %b %Y %H:%M')} (local time)", f"{'Debited from' if t.direction == 'debit' else 'Credited to'}: A/c {t.victim_account_masked.value}", f"{label if t.direction == 'debit' else 'Sender'}: {to}", ""])
    return "\n".join(lines) + "\nScenario: " + s["notes"]
