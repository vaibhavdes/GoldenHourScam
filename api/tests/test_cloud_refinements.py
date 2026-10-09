import pytest
from fastapi import HTTPException

from test_api import client  # shared offline model fixture
from app.models import Field_, Transaction, now
from app.store import MemoryStore


def test_public_input_validation(client):
    for body in ({"country": "ZZ"}, {"language": "id"}, {"victim_age": -1}):
        assert client.post("/cases", json=body).status_code == 422
    assert client.post("/cases", json={"country": "in"}).json()["country"] == "IN"
    for text in ("", "x" * 10001):
        assert client.post("/precheck", json={"text": text}).status_code == 422
    case = client.post("/cases", json={}).json()
    client.headers["X-Case-Secret"] = case["secret"]
    assert client.post(f"/cases/{case['id']}/ack", json={"ack_number": "   "}).status_code == 422
    assert client.post(f"/cases/{case['id']}/steps", json={"step_id": "invented"}).status_code == 422
    assert client.post("/console/clusters/attribution", json={"case_ids": [case["id"]], "held_amount": -1}).status_code == 422


def test_helper_never_exposes_unconfirmed_or_invalid_payments(client):
    from app.store import get_store
    created = client.post("/cases", json={}).json()
    client.headers["X-Case-Secret"] = created["secret"]
    case = get_store().get(created["id"])
    case.transactions = [Transaction(amount=Field_(value="999999", valid=True),
        utr=Field_(value="123456789012", valid=True)), Transaction(confirmed=True,
        amount=Field_(value="888888", valid=False), utr=Field_(value="234567890123", valid=False))]
    get_store().put(case)
    token = client.post(f"/cases/{case.id}/share").json()["token"]
    result = client.get(f"/shared/{token}")
    assert result.status_code == 200
    assert all(t == {"amount": None, "time": None, "reference": None} for t in result.json()["transactions"])


def test_voice_completion_records_report_time_and_rejects_unknown_steps(client):
    from app.live.proxy import run_tool
    from app.store import get_store
    created = client.post("/cases", json={}).json()
    assert run_tool(created["id"], "mark_step_done", {"step_id": "call_helpline"})["ok"]
    case = get_store().get(created["id"])
    item = next(s for s in case.steps if s.id == "call_helpline")
    assert item.done and item.done_at and case.reported_at
    assert case.audit[-1].actor == "victim_voice"
    assert "error" in run_tool(created["id"], "mark_step_done", {"step_id": "invented"})
    assert "revision" not in client.get(f"/cases/{case.id}", headers={"X-Case-Secret": created["secret"]}).json()


def test_stale_write_cannot_overwrite_completed_steps():
    from app.models import Case
    store = MemoryStore()
    case = Case(); store.put(case)
    upload, voice = store.get(case.id), store.get(case.id)
    voice.reported_at = now(); store.put(voice)
    with pytest.raises(HTTPException) as error:
        store.put(upload)
    assert error.value.status_code == 409
    assert store.get(case.id).reported_at == voice.reported_at


def test_reminder_hook_checks_audience_and_service_identity(client, monkeypatch):
    from app.config import get_settings
    from google.oauth2 import id_token
    monkeypatch.setenv("TASKS_SERVICE_ACCOUNT", "tasks@test-project.iam.gserviceaccount.com")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://service.example.test")
    get_settings.cache_clear()
    assert client.post("/internal/reminders/GH-X").status_code == 403
    seen = []
    def verified(token, request, audience):
        seen.append(audience)
        return {"email": "tasks@test-project.iam.gserviceaccount.com", "email_verified": True}
    monkeypatch.setattr(id_token, "verify_oauth2_token", verified)
    assert client.post("/internal/reminders/GH-X", headers={"Authorization": "Bearer test"}).status_code == 200
    assert seen == ["https://service.example.test"]
    monkeypatch.setattr(id_token, "verify_oauth2_token", lambda *a, **kw: {"email": "wrong@example.com", "email_verified": True})
    assert client.post("/internal/reminders/GH-X", headers={"Authorization": "Bearer test"}).status_code == 403


def test_all_uploads_are_validated_before_any_storage(client, monkeypatch):
    from app.store import get_store
    case = client.post("/cases", json={}).json()
    client.headers["X-Case-Secret"] = case["secret"]
    saved = []
    monkeypatch.setattr(get_store(), "save_evidence", lambda *args: saved.append(args))
    result = client.post(f"/cases/{case['id']}/evidence", files=[
        ("files", ("valid.txt", b"synthetic", "text/plain")),
        ("files", ("empty.txt", b"", "text/plain"))])
    assert result.status_code == 400 and not saved
    assert client.post(f"/cases/{case['id']}/evidence", files={"files": ("unsupported.gif", b"GIF89a", "image/gif")}).status_code == 415


def test_extraction_outage_preserves_files_and_allows_manual_details(client, monkeypatch):
    from app.store import get_store
    from app.models import Beneficiary, Rail
    case = client.post("/cases", json={}).json()
    client.headers["X-Case-Secret"] = case["secret"]
    def unavailable(*args):
        raise RuntimeError("upstream credential string must never appear in response")
    monkeypatch.setattr("app.main.extract_svc.extract", unavailable)
    response = client.post(f"/cases/{case['id']}/evidence", files={"files": ("receipt.txt", b"synthetic", "text/plain")})
    assert response.status_code == 503
    assert "credential string" not in response.text
    assert len(get_store().get(case["id"]).evidence) == 1
    def entered(value):
        return Field_(value=value, status="user")
    transaction = Transaction(rail=Rail.UPI, utr=entered("123456789012"), amount=entered("1000.00"), timestamp=entered("2026-10-03T10:00:00+05:30"), victim_account_masked=entered("XX4821"), beneficiary=Beneficiary(vpa=entered("synthetic.payee@oksbi")))
    result = client.put(f"/cases/{case['id']}/confirm", json={"transactions": [transaction.model_dump(mode="json")]})
    assert result.status_code == 200
    assert result.json()["transactions"][0]["utr"]["valid"]
    assert client.get(f"/cases/{case['id']}/pack").json()["ready"]


def test_classifier_outage_keeps_extracted_values_and_hindi_guidance(client, monkeypatch, caplog):
    from app.services.classify import classify
    from app.models import Case
    def unavailable(**kwargs):
        raise RuntimeError("sensitive provider detail")
    monkeypatch.setattr("app.services.classify.generate_json", unavailable)
    case = Case(language="hi", transactions=[Transaction(amount=Field_(value="1000"))])
    result = classify(case, [])
    assert result.transactions[0].amount.value == "1000"
    assert "1930" in result.explanation and "बैंक" in result.explanation
    response = client.post("/precheck", json={"text": "A caller wants money"})
    assert response.status_code == 503
    assert "AI precheck unavailable: RuntimeError" in caplog.text
    assert "sensitive provider detail" not in caplog.text + response.text


def test_identical_account_digits_in_different_countries_do_not_link():
    from app.models import Beneficiary, Case
    from app.tools.linking import clusters, linked_count
    cases = [Case(country=country, transactions=[Transaction(beneficiary=Beneficiary(account=Field_(value="123456789012", valid=True)))]) for country in ("IN", "MY")]
    assert not clusters(cases)
    assert linked_count(cases[0], cases) == 0


def test_credit_cannot_appear_as_a_loss_in_complaint_draft(client):
    from app.models import Case
    from app.services.filing import build_pack
    case = Case(transactions=[Transaction(direction="credit", confirmed=True, amount=Field_(value="123456", valid=True))])
    result = build_pack(case)
    assert not result.ready
    assert "123456" not in result.narrative and "123456" not in result.bank_letter
