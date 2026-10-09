import json
import pytest
from fastapi import HTTPException

from app.models import Beneficiary, Case, Field_, Rail, Transaction
from app.services import filing, responder
from app.tools.validators import validate_case


def entered(value):
    return Field_(value=value, status="user")


def valid_case():
    case = Case(transactions=[Transaction(rail=Rail.UPI, confirmed=True,
        utr=entered("123456789012"), amount=entered("49999.00"),
        timestamp=entered("2026-10-06T10:00:00+05:30"), victim_account_masked=entered("XX4821"),
        beneficiary=Beneficiary(vpa=entered("rbi.verify.cell@oksbi")))])
    return validate_case(case)


def test_invalid_utr_is_excluded_from_every_draft(monkeypatch):
    monkeypatch.setattr(filing, "generate_text", lambda **kw: "")
    case = valid_case()
    case.transactions[0].utr = entered("BAD")
    validate_case(case)
    pack = filing.build_pack(case)
    assert not pack.ready
    assert "BAD" not in json.dumps(pack.model_dump())
    assert next(f for f in pack.fields if f["key"] == "utr")["value"].startswith("[please check:")
    with pytest.raises(HTTPException) as error:
        responder.hold_request(case, [case])
    assert error.value.status_code == 409


def test_unconfirmed_values_are_excluded_and_hold_is_rejected(monkeypatch):
    monkeypatch.setattr(filing, "generate_text", lambda **kw: "")
    case = valid_case()
    case.transactions[0].confirmed = False
    pack = filing.build_pack(case)
    assert not pack.ready
    assert "123456789012" not in json.dumps(pack.model_dump())
    with pytest.raises(HTTPException) as error:
        responder.hold_request(case, [case])
    assert error.value.status_code == 409


def test_reviewed_pack_is_ready_and_portal_safe(monkeypatch):
    monkeypatch.setattr(filing, "generate_text", lambda **kw: "made up UTR 999999999999")
    case = valid_case()
    pack = filing.build_pack(case)
    assert pack.ready and pack.narrative_ok
    assert len(pack.narrative) >= 200
    assert "@" not in pack.narrative and "rbi.verify.cell at oksbi" in pack.narrative
    assert "999999999999" not in pack.narrative
    assert responder.hold_request(case, [case]).action == "HOLD_DISPUTED_AMOUNT"


def test_zero_evidence_still_has_urgent_call_guidance(monkeypatch):
    monkeypatch.setattr(filing, "generate_text", lambda **kw: "")
    pack = filing.build_pack(Case())
    assert not pack.ready
    assert "1930" in pack.call_script[0]["q"]
