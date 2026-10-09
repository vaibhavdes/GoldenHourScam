from app.models import Case, Field_, Rail, Transaction
from app.services import extract
from app.tools.validators import validate_case


def case_with_claim(label=None):
    return Case(transactions=[Transaction(rail=Rail.UPI, utr=Field_(
        value="123456789012", source_quote="UTR 123456789012", source_file=label,
        confidence=.99, status="checked", valid=True))])


def test_independent_text_check_rejects_fabricated_quote():
    case = case_with_claim()
    case.evidence_text = {"receipt": "UTR 999999999999"}
    validate_case(case)
    assert case.transactions[0].utr.status == "read"
    assert not case.transactions[0].utr.valid
    case.evidence_text["receipt"] = "UTR 123456789012"
    validate_case(case)
    assert case.transactions[0].utr.status == "checked"
    assert case.transactions[0].utr.valid
    assert case.transactions[0].utr.source_file == "receipt"
    assert case.transactions[0].utr.source_quote == "UTR 123456789012"


def test_source_file_is_respected_and_longer_id_is_not_a_match():
    case = case_with_claim("sms")
    case.evidence_text = {"sms": "UTR 1234567890123", "receipt": "UTR 123456789012"}
    validate_case(case)
    assert not case.transactions[0].utr.valid
    case.transactions[0].utr.source_file = None
    validate_case(case)
    assert case.transactions[0].utr.valid


def test_each_binary_file_has_separate_lite_transcription(monkeypatch):
    calls = []
    monkeypatch.setattr(extract, "transcribe", lambda **kw: calls.append(kw) or "visible text")
    monkeypatch.setattr(extract, "generate_json", lambda **kw: {"transactions": [], "suspects": []})
    case = Case()
    extract.extract(case, [("one", "image/png", b"image"), ("two", "application/pdf", b"pdf"),
                          ("three", "text/plain", b"raw text")])
    assert [c["data"] for c in calls] == [b"image", b"pdf"]
    assert all(c["model"] == extract.get_settings().model_lite for c in calls)
    assert case.evidence_text == {"one": "visible text", "two": "visible text", "three": "raw text"}


def test_source_basename_matches_only_a_unique_uploaded_file():
    case = case_with_claim("receipt.png")
    case.evidence_text = {"upload123 receipt.png": "UTR 123456789012"}
    validate_case(case)
    assert case.transactions[0].utr.valid
    case.transactions[0].utr.source_file = "receipt.png"
    case.evidence_text["other456 receipt.png"] = "UTR 999999999999"
    validate_case(case)
    assert not case.transactions[0].utr.valid


def test_visible_local_timestamp_checks_iso_without_inventing_a_time():
    transaction = Transaction(rail=Rail.UPI, timestamp=Field_(
        value="2026-10-06T20:17:00+05:30", source_file="receipt.png"))
    case = Case(transactions=[transaction], evidence_text={"id receipt.png": "06 Oct 2026, 08:17 PM"})
    validate_case(case)
    assert transaction.timestamp.valid
    transaction.timestamp.value = "2026-10-06T20:18:00+05:30"
    validate_case(case)
    assert not transaction.timestamp.valid
def test_amount_can_be_checked_with_attached_currency_prefix():
    from app.models import Field_
    from app.tools.validators import grounded
    field = Field_(value="30100.00")
    assert grounded(field, "Paid RM30,100.00", amount=True)
    assert grounded(field, "Amount MYR30100.00", amount=True)
    assert grounded(field, "Debited INR30100.00", amount=True)
    assert grounded(field, "Paid SGD30,100.00", amount=True)
    assert not grounded(field, "Reference BRM30100.00", amount=True)
    assert not grounded(field, "Paid RM30,100.50", amount=True)


def test_source_file_echoing_prompt_label_is_normalised():
    # Gemini sometimes returns the prompt label verbatim, e.g. "FILE <id> receipt_1.png".
    case = case_with_claim("FILE d52ca7b4a4 receipt_1.png")
    case.evidence_text = {"d52ca7b4a4 receipt_1.png": "UPI transaction ID 123456789012"}
    validate_case(case)
    assert case.transactions[0].utr.status == "checked"
    assert case.transactions[0].utr.valid


def test_source_file_given_as_evidence_id_only():
    case = case_with_claim("53e9b81402")
    case.evidence_text = {"53e9b81402 receipt_1.png": "UPI transaction ID 123456789012",
                          "aa11bb22cc sms_1.png": "Refno 999999999999"}
    validate_case(case)
    assert case.transactions[0].utr.status == "checked"
