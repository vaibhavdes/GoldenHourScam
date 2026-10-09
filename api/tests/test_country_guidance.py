from app.live.proxy import system_prompt
from app.models import Case, Field_, Transaction
from app.services import filing, lockdown
from app.packs import load_pack


def test_my_requires_separate_police_report_after_emergency_contact():
    case = Case(country="MY")
    report = next(s for s in lockdown.sos_steps(case) if s.id == "file_report")
    assert "separate police report" in report.label
    assert "24 hours" in report.label
    assert "nearest police station within 24 hours" in system_prompt(case)
    assert "separate police report" in filing.build_call_script(case)[0]["a"]
    pack = load_pack("MY")
    assert "semakmule" not in pack["portal"]["url"]
    assert "treated as a police report" not in str(pack)
    malay = next(s for s in lockdown.sos_steps(Case(country="MY", language="ms")) if s.id == "file_report")
    assert "laporan polis berasingan" in malay.label


def test_sg_bank_step_first():
    case = Case(country="SG")
    steps = lockdown.sos_steps(case)
    assert [s.id for s in steps[:3]] == ["bank_block", "call_helpline", "file_report"]
    assert "24/7" in steps[0].label
    assert "1799" in steps[1].label
    assert "bank first" in filing.build_call_script(case)[0]["q"].lower()
    assert "kill switch first, then call 1799" in system_prompt(case)


def test_unknown_timestamp_never_uses_case_creation_time():
    case = Case(transactions=[Transaction(timestamp=Field_(value="2026-10-03T10:00:00+05:30"))])
    assert case.first_txn_time() is None
    case.reported_transfer_time = Field_(value="2026-10-03T10:00:00+05:30", status="user", valid=True)
    assert case.first_txn_time().isoformat() == "2026-10-03T10:00:00+05:30"
