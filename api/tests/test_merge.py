import pytest

from app.models import Beneficiary, Case, Field_, Rail, Transaction
from app.services.extract import merge_transactions


def field(value, confidence=.9):
    return Field_(value=value, source_quote=value, confidence=confidence)


def sms():
    return Transaction(rail=Rail.UPI, utr=field("123456789012"), amount=field("49999.00"),
                       timestamp=field("2026-10-06T10:00:00+05:30"))


def receipt():
    return Transaction(rail=Rail.UPI, utr=field("123456789012"), amount=field("49999"),
                       timestamp=field("2026-10-06T10:00:00+05:30"),
                       beneficiary=Beneficiary(vpa=field("rbi.verify.cell@oksbi")))


@pytest.mark.parametrize("reverse", [False, True])
def test_complementary_uploads_preserve_fields(reverse):
    items = [sms(), receipt()]
    if reverse:
        items.reverse()
    case = Case(evidence_text={"fixture": "123456789012 49999.00 50000 rbi.verify.cell@oksbi 2026-10-06T10:00:00+05:30 2026-10-06T10:01:30+05:30 different@oksbi"})
    for item in items:
        merge_transactions(case, [item])
    assert len(case.transactions) == 1
    t = case.transactions[0]
    assert t.utr.valid and t.amount.valid and t.beneficiary.vpa.valid
    assert t.beneficiary.vpa.value == "rbi.verify.cell@oksbi"


def test_conflict_retains_higher_confidence_and_requires_review():
    case = Case(evidence_text={"fixture": "123456789012 49999.00 50000 rbi.verify.cell@oksbi 2026-10-06T10:00:00+05:30 2026-10-06T10:01:30+05:30 different@oksbi"})
    a, b = sms(), receipt()
    b.amount = field("50000", .99)
    merge_transactions(case, [a, b])
    amount = case.transactions[0].amount
    assert amount.value == "50000"
    assert not amount.valid
    assert amount.issue == "Conflicting values in your screenshots: 49999.00 vs 50000"


def test_missing_utr_matches_only_with_amount_time_and_beneficiary():
    case = Case(evidence_text={"fixture": "123456789012 49999.00 50000 rbi.verify.cell@oksbi 2026-10-06T10:00:00+05:30 2026-10-06T10:01:30+05:30 different@oksbi"})
    a, b = receipt(), receipt()
    a.utr = Field_()
    a.rail = Rail.UNKNOWN
    b.timestamp = field("2026-10-06T10:01:30+05:30")
    merge_transactions(case, [a, b])
    assert len(case.transactions) == 1
    assert case.transactions[0].utr.value == "123456789012"
    assert case.transactions[0].rail == Rail.UPI
    c = receipt()
    c.utr = Field_()
    c.beneficiary.vpa = field("different@oksbi")
    merge_transactions(case, [c])
    assert len(case.transactions) == 2
