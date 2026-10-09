"""Unit tests for deterministic tools (no network / no Gemini)."""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models import Beneficiary, Case, Field_, Rail, ScamType, Suspect, Transaction  # noqa: E402
from app.packs import load_pack  # noqa: E402
from app.services import filing, lockdown, responder  # noqa: E402
from app.tools.attribution import pro_rata  # noqa: E402
from app.tools.linking import clusters, linked_count  # noqa: E402
from app.tools.sanitize import portal_ok, sanitize  # noqa: E402
from app.tools.score import score_case  # noqa: E402
from app.tools.validators import grounded, validate_transaction as _validate_transaction  # noqa: E402

SMS = "Rs.49,999.00 debited from A/c XX4821 on 03-10-26 to VPA abc.trade@okaxis UPI Ref No 627512345678. Not you? Call 18001234567"


def f(v, q=SMS, c=0.9):
    return Field_(value=v, source_quote=q, confidence=c)


def txn(utr="627512345678", amount="49999.00", vpa="abc.trade@okaxis", ts=None):
    ts = ts or datetime.now(timezone.utc).isoformat()
    return Transaction(rail=Rail.UPI, utr=f(utr), amount=f(amount), timestamp=Field_(value=ts),
                       victim_account_masked=f("XX4821"), beneficiary=Beneficiary(vpa=f(vpa)), confirmed=True)


def validate_transaction(t, country):
    return _validate_transaction(t, country, {"fixture": SMS + " VPA mule1@ybl VPA other@ybl VPA mule@ybl UTR 111122223333 UTR 444455556666 " + (t.timestamp.value or "")})


# ---- validators
def test_grounded_amount_with_commas():
    assert grounded(f("49999.00"), SMS, amount=True)


def test_helpline_number_is_not_a_utr():
    t = validate_transaction(txn(utr="18001234567"), "IN")
    assert not t.utr.valid  # 11 digits -> wrong format


def test_invented_utr_rejected():
    t = validate_transaction(txn(utr="999999999999"), "IN")
    assert not t.utr.valid and "not found" in t.utr.issue


def test_valid_utr_and_vpa():
    t = validate_transaction(txn(), "IN")
    assert t.utr.valid and t.beneficiary.vpa.valid and t.amount.valid


def test_masked_beneficiary_account_flagged():
    t = txn()
    t.beneficiary.account = f("XX9911", q="to A/c XX9911")
    t = validate_transaction(t, "IN")
    assert not t.beneficiary.account.valid


# ---- sanitizer
def test_sanitize_ncrp():
    forbidden = load_pack("IN")["portal"]["narrative_forbidden_chars"]
    s = sanitize("I paid #1 @ 10:31! It's a 'scam' & more ~|", forbidden)
    assert not any(ch in s for ch in forbidden)
    assert "and" in s


def test_portal_ok_min_length():
    assert not portal_ok("short", "", 200)
    assert portal_ok("x" * 200, "#", 200)


# ---- score
def test_score_decays_with_time():
    fresh = Case(transactions=[txn(ts=(datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat())])
    old = Case(transactions=[txn(ts=(datetime.now(timezone.utc) - timedelta(hours=30)).isoformat())])
    for c in (fresh, old):
        c.transactions = [validate_transaction(t, "IN") for t in c.transactions]
    assert score_case(fresh).score > score_case(old).score


# ---- linking + attribution
def test_linking_shared_vpa():
    a = Case(transactions=[validate_transaction(txn(vpa="mule1@ybl"), "IN")])
    b = Case(transactions=[validate_transaction(txn(vpa="mule1@ybl", utr="111122223333"), "IN")])
    c = Case(transactions=[validate_transaction(txn(vpa="other@ybl", utr="444455556666"), "IN")])
    cl = clusters([a, b, c])
    assert len(cl) == 1 and set(cl[0]["case_ids"]) == {a.id, b.id}
    assert linked_count(a, [a, b, c]) == 1


def test_pro_rata_reconciles():
    rows = pro_rata(1000.00, {"A": 333.33, "B": 333.33, "C": 333.34, "D": 1.0})
    assert abs(sum(r["share"] for r in rows) - 1000.00) < 1e-9


def test_pro_rata_held_capped_at_total():
    rows = pro_rata(5000, {"A": 100, "B": 300})
    assert abs(sum(r["share"] for r in rows) - 400) < 1e-9


# ---- lockdown + filing (template paths, no LLM)
def test_lockdown_differs_by_type():
    a = Case(scam_type=ScamType.DIGITAL_ARREST)
    b = Case(scam_type=ScamType.PHISHING_OTP)
    assert [s.label for s in lockdown.lockdown(a)] != [s.label for s in lockdown.lockdown(b)]


def test_fields_and_missing():
    c = Case(scam_type=ScamType.DIGITAL_ARREST, transactions=[validate_transaction(txn(), "IN")],
             suspects=[Suspect(phone="+91 9876543210")])
    fields, missing = filing.build_fields(c)
    utr = next(x for x in fields if x["key"] == "utr")
    assert utr["ok"] and utr["value"] == "627512345678"
    assert not any(x["label"] in missing for x in fields if x["required"])


def test_call_script_contains_utr():
    c = Case(scam_type=ScamType.INVESTMENT, transactions=[validate_transaction(txn(), "IN")])
    script = filing.build_call_script(c)
    assert any("627512345678" in s["a"] for s in script)


def test_hold_request_defaults_to_disputed_amount():
    c = Case(transactions=[validate_transaction(txn(), "IN")])
    hr = responder.hold_request(c, [c])
    assert hr.action == "HOLD_DISPUTED_AMOUNT"
    assert "ONLY on the disputed amount" in hr.text


def test_no_full_freeze_option():
    import inspect
    from app.main import HoldReq
    assert "full_freeze" not in HoldReq.model_fields
    assert "justification" not in HoldReq.model_fields
    assert "full_freeze" not in inspect.signature(responder.hold_request).parameters
    assert not hasattr(responder, "full_freeze_allowed")


def test_phone_only_links_do_not_raise_priority():
    cases = [Case(transactions=[validate_transaction(txn(vpa=f"distinct{i}@ybl"), "IN")],
                  suspects=[Suspect(phone="+919999000000", url="https://fake.example")]) for i in range(3)]
    assert linked_count(cases[0], cases) == 0
    assert clusters(cases) == []
    row = next(row for row in responder.queue(cases) if row["case_id"] == cases[0].id)
    assert row["linked"] == 0
    assert row["score"] == score_case(cases[0], linked_cases=0).score
