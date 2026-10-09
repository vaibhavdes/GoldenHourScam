from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from app.models import Beneficiary, Case, Field_, Rail, Transaction
from app.services import filing, responder
from app.services.extract import merge_transactions
from app.tools.validators import validate_case


def entered(value):
    return Field_(value=value, status="user")


def reviewed():
    return validate_case(Case(transactions=[Transaction(rail=Rail.UPI, confirmed=True,
        utr=entered("123456789012"), amount=entered("10000.00"),
        timestamp=entered((datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()),
        victim_account_masked=entered("XX4821"),
        beneficiary=Beneficiary(vpa=entered("synthetic.payee@oksbi")))]))


def test_unknown_rail_cannot_validate_bad_reference_or_create_hold():
    case = reviewed()
    case.transactions[0].rail = Rail.UNKNOWN
    case.transactions[0].utr = entered("BAD")
    validate_case(case)
    assert not case.transactions[0].utr.valid
    with pytest.raises(HTTPException) as error:
        responder.hold_request(case, [case])
    assert error.value.status_code == 409


def test_credit_cannot_be_drafted_as_a_disputed_outgoing_hold():
    case = reviewed()
    case.transactions[0].direction = "credit"
    with pytest.raises(HTTPException) as error:
        responder.hold_request(case, [case])
    assert error.value.status_code == 409


def test_future_timestamp_is_not_valid():
    case = reviewed()
    case.transactions[0].timestamp = entered((datetime.now(timezone.utc) + timedelta(days=1)).isoformat())
    validate_case(case)
    assert not case.transactions[0].timestamp.valid
    assert case.first_txn_time() is None


def test_reupload_does_not_silently_clear_a_conflict():
    case = reviewed()
    case.evidence_text = {"receipt": "123456789012 10000.00 20000.00 synthetic.payee@oksbi"}
    incoming = case.transactions[0].model_copy(deep=True)
    incoming.amount = Field_(value="20000.00", confidence=.99)
    merge_transactions(case, [incoming])
    assert not case.transactions[0].amount.valid
    merge_transactions(case, [incoming.model_copy(deep=True)])
    assert not case.transactions[0].amount.valid
    assert "Conflicting values" in case.transactions[0].amount.issue


def test_unreviewed_timeline_and_invented_payee_do_not_enter_narrative(monkeypatch):
    case = reviewed()
    prompts = []
    def fake(**kw):
        prompts.append(kw["prompt"])
        return "I transferred 10000.00 with reference 123456789012 to invented@oksbi. Reference BAD."
    monkeypatch.setattr(filing, "generate_text", fake)
    text, _ = filing.build_narrative(case, [{"event": "Reference BAD, paid invented@oksbi"}])
    assert "BAD" not in prompts[0]
    assert "invented" not in prompts[0]
    assert "BAD" not in text
    assert "invented" not in text
    assert "synthetic.payee at oksbi" in text
