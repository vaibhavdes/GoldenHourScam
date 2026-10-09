"""API smoke tests with Gemini calls stubbed out."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("OPEN_WORKSPACE", "false")
    monkeypatch.setenv("CASE_COLLECTION", "cases")
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("CONSOLE_KEY", "test-console-key")
    from app.config import get_settings
    get_settings.cache_clear()
    from app import llm, main, store
    monkeypatch.setattr(store, "_store", store.MemoryStore())

    def fake_json(**kw):
        if "Extract" in str(kw.get("parts", [])[-1:]):
            return {"transactions": [{
                "direction": "debit", "rail": "UPI", "currency": "INR", "is_fraud_related": True,
                "amount": {"value": "49999.00", "confidence": 0.95, "source_quote": "Rs.49,999.00 debited"},
                "utr": {"value": "627512345678", "confidence": 0.95, "source_quote": "UPI Ref No 627512345678"},
                "timestamp": {"value": "2026-10-03T10:31:00+05:30", "confidence": 0.9},
                "beneficiary_vpa": {"value": "abc.trade@okaxis", "confidence": 0.9,
                                    "source_quote": "to VPA abc.trade@okaxis"}}],
                "suspects": [{"phone": "+919876543210", "claimed_identity": "CBI officer"}],
                "timeline": [{"time": "10:02", "event": "Video call from fake CBI officer"}]}
        return {"scam_type": "digital_arrest", "confidence": 0.9, "red_flags": ["video call arrest"],
                "explanation": "This was a scam.", "verdict": "likely_scam", "advice": "Hang up."}

    monkeypatch.setattr(llm, "generate_json", fake_json)
    monkeypatch.setattr("app.services.extract.generate_json", fake_json)
    monkeypatch.setattr("app.services.classify.generate_json", fake_json)
    monkeypatch.setattr("app.services.filing.generate_text", lambda **kw: "")
    monkeypatch.setattr("app.services.responder.generate_text", lambda **kw: "explained")
    return TestClient(main.app, headers={"X-Console-Key": "test-console-key"})


def test_full_victim_flow(client):
    case = client.post("/cases", json={"country": "IN", "language": "en"}).json()
    client.headers["X-Case-Secret"] = case["secret"]
    r = client.post(f"/cases/{case['id']}/evidence",
                    files=[("files", ("sms.txt", b"Rs.49,999.00 debited ... UPI Ref No 627512345678 to VPA abc.trade@okaxis 2026-10-03T10:31:00+05:30", "text/plain"))])
    assert r.status_code == 200, r.text
    c = r.json()["case"]
    assert c["scam_type"] == "digital_arrest"
    assert c["transactions"][0]["utr"]["valid"] is True
    assert "uri" not in c["evidence"][0]
    assert "evidence_text" not in c
    confirmed = client.put(f"/cases/{case['id']}/confirm", json={"transactions": c["transactions"], "suspects": c["suspects"]})
    assert confirmed.status_code == 200
    pack = client.get(f"/cases/{case['id']}/pack").json()
    assert pack["narrative_ok"] is True
    assert any(f["key"] == "utr" and f["ok"] for f in pack["fields"])
    q = client.get("/console/queue").json()
    assert q and q[0]["case_id"] == case["id"]
    hr = client.post(f"/console/cases/{case['id']}/hold-request", json={}).json()
    assert hr["action"] == "HOLD_DISPUTED_AMOUNT"


def test_share_link(client):
    case = client.post("/cases", json={"country": "MY"}).json()
    client.headers["X-Case-Secret"] = case["secret"]
    tok = client.post(f"/cases/{case['id']}/share").json()["token"]
    r = client.get(f"/shared/{tok}")
    assert r.status_code == 200 and r.json()["helplines"][0]["number"] == "997"
    assert client.get("/shared/garbage").status_code == 403


def test_case_capability_and_private_response_fields(client):
    from app.store import get_store
    first = client.post("/cases", json={}).json()
    second = client.post("/cases", json={}).json()
    assert len(first["secret"]) >= 32 and first["secret"] != second["secret"]
    stored = get_store().get(first["id"])
    assert stored.secret_hash and stored.secret_hash != first["secret"]
    assert "secret_hash" not in first and "audit" not in first
    base = f"/cases/{first['id']}"
    for method, path, body in [("GET", "", None), ("GET", "/pack", None),
        ("GET", "/reminders", None), ("POST", "/share", None),
        ("PUT", "/confirm", {"transactions": []}),
        ("POST", "/steps", {"step_id": "evidence"}),
        ("POST", "/ack", {"ack_number": "synthetic"})]:
        assert client.request(method, base + path, json=body).status_code == 403
        assert client.request(method, base + path, json=body,
                              headers={"X-Case-Secret": second["secret"]}).status_code == 403
    assert client.post(base + "/evidence", files={"files": ("x.txt", b"x", "text/plain")}).status_code == 403
    client.headers["X-Case-Secret"] = first["secret"]
    view = client.get(base).json()
    assert view["id"] == first["id"]
    assert all(k not in view for k in ("secret", "secret_hash", "audit", "evidence_text"))
    with pytest.raises(Exception) as denied:
        with client.websocket_connect(f"/live/{first['id']}?secret=wrong"):
            pass
    assert getattr(denied.value, "code", None) == 1008


def test_every_console_route_requires_passcode(client):
    client.headers.pop("X-Console-Key")
    for method, path, body in [("GET", "/console/queue", None),
        ("GET", "/console/cases/GH-X", None), ("GET", "/console/clusters", None),
        ("POST", "/console/cases/GH-X/hold-request", {}),
        ("POST", "/console/clusters/attribution", {"case_ids": [], "held_amount": 0})]:
        assert client.request(method, path, json=body).status_code == 403
        assert client.request(method, path, json=body, headers={"X-Console-Key": "wrong"}).status_code == 403
    assert client.get("/console/queue", headers={"X-Console-Key": "test-console-key"}).status_code == 200
    assert client.get("/health").status_code == 200
    assert client.get("/packs").status_code == 200


def test_confirmation_does_not_trust_client_checked_status(client):
    from app.models import Field_, Rail, Transaction
    from app.store import get_store
    case = client.post("/cases", json={}).json()
    stored = get_store().get(case["id"])
    stored.transactions = [Transaction(rail=Rail.UPI, utr=Field_(value="123456789012", status="read"))]
    get_store().put(stored)
    transaction = stored.transactions[0].model_dump(mode="json")
    transaction["utr"].update(status="checked", valid=True, source_quote="123456789012")
    client.headers["X-Case-Secret"] = case["secret"]
    result = client.put(f"/cases/{case['id']}/confirm", json={"transactions": [transaction]}).json()
    assert not result["transactions"][0]["utr"]["valid"]
    assert result["transactions"][0]["utr"]["status"] == "read"
    transaction["utr"].update(status="user", source_quote=None)
    result = client.put(f"/cases/{case['id']}/confirm", json={"transactions": [transaction]}).json()
    assert result["transactions"][0]["utr"]["valid"]
    assert result["transactions"][0]["utr"]["status"] == "user"


def test_hold_endpoint_rejects_invalid_reference(client):
    from app.models import Field_, Rail, Transaction
    from app.store import get_store
    case = client.post("/cases", json={}).json()
    stored = get_store().get(case["id"])
    stored.transactions = [Transaction(rail=Rail.UPI, confirmed=True, utr=Field_(value="BAD"))]
    get_store().put(stored)
    response = client.post(f"/console/cases/{case['id']}/hold-request", json={})
    assert response.status_code == 409
    assert "BAD" not in response.text


def test_optional_transfer_time_requires_owner_and_timezone(client):
    from datetime import datetime, timedelta, timezone
    case = client.post("/cases", json={}).json()
    url = f"/cases/{case['id']}/transfer-time"
    assert client.put(url, json={"timestamp": "2026-10-03T10:00:00+05:30"}).status_code == 403
    client.headers["X-Case-Secret"] = case["secret"]
    assert client.put(url, json={"timestamp": "2026-10-03T10:00:00"}).status_code == 400
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    assert client.put(url, json={"timestamp": future}).status_code == 400
    result = client.put(url, json={"timestamp": "2026-10-03T10:00:00+05:30"})
    assert result.status_code == 200
    assert result.json()["reported_transfer_time"]["status"] == "user"


def test_live_uploaded_case_appears_in_queue_with_six_peers(client, monkeypatch):
    from app.models import Beneficiary, Case, Field_, Rail, Transaction
    from app.store import get_store
    from app.tools.validators import validate_case
    for i in range(6):
        peer = Case(id=f"GH-PEER-{i}", synthetic=True, transactions=[Transaction(
            rail=Rail.UPI, confirmed=True, beneficiary=Beneficiary(
                vpa=Field_(value="rbi.verify.cell@oksbi", status="user")))])
        validate_case(peer)
        get_store().put(peer)
    def two_transfers(**kw):
        transactions = []
        for utr, amount in (("123456789012", "240000.00"), ("234567890123", "245000.00")):
            def f(value):
                return {"value": value, "confidence": .99, "source_quote": value}
            transactions.append({"rail": "UPI", "direction": "debit", "is_fraud_related": True,
                "utr": f(utr), "amount": f(amount), "beneficiary_vpa": f("rbi.verify.cell@oksbi"),
                "timestamp": f("2026-10-06T10:00:00+05:30"), "victim_account_masked": f("XX4821")})
        return {"transactions": transactions, "suspects": [], "timeline": []}
    monkeypatch.setattr("app.services.extract.generate_json", two_transfers)
    created = client.post("/cases", json={"country": "IN"}).json()
    client.headers["X-Case-Secret"] = created["secret"]
    text = b"UTR 123456789012 Amount 240000.00 UTR 234567890123 Amount 245000.00 VPA rbi.verify.cell@oksbi A/c XX4821 2026-10-06T10:00:00+05:30"
    result = client.post(f"/cases/{created['id']}/evidence", files={"files": ("synthetic.txt", text, "text/plain")})
    assert result.status_code == 200
    assert len(result.json()["case"]["transactions"]) == 2
    queue = client.get("/console/queue").json()
    live_row = next(row for row in queue if row["case_id"] == created["id"])
    assert live_row["linked"] == 6
    assert not any(row["case_id"] == "GH-CASE-SUNITA" for row in queue)


def test_console_and_helper_remove_victim_identifiers_from_free_text(client, monkeypatch):
    from app.models import Beneficiary, Field_, Rail, Transaction
    from app.store import get_store
    monkeypatch.setenv("USE_DLP", "false")
    from app.config import get_settings
    get_settings.cache_clear()
    created = client.post("/cases", json={"victim_name": "Synthetic Victim"}).json()
    client.headers["X-Case-Secret"] = created["secret"]
    case = get_store().get(created["id"])
    private = "Synthetic Victim XX4821 9876543210"
    case.explanation = private
    case.narrative = private
    case.timeline = [{"event": private}]
    case.transactions = [Transaction(rail=Rail.UPI, confirmed=True,
        utr=Field_(value="123456789012", valid=True, source_quote=private, source_file=private),
        victim_account_masked=Field_(value="XX4821", valid=True),
        beneficiary=Beneficiary(vpa=Field_(value="synthetic.payee@oksbi", valid=True, source_quote=private)))]
    get_store().put(case)
    console = client.get(f"/console/cases/{case.id}?explain=false")
    token = client.post(f"/cases/{case.id}/share").json()["token"]
    helper = client.get(f"/shared/{token}")
    assert console.status_code == helper.status_code == 200
    for value in ("Synthetic Victim", "XX4821", "9876543210"):
        assert value not in console.text
        assert value not in helper.text
    assert "synthetic.payee@oksbi" in console.text
    assert "source_quote" not in console.text and "evidence_text" not in console.text


def test_upload_rejects_oversize_before_storage(client, monkeypatch):
    from app.store import get_store
    created = client.post("/cases", json={}).json()
    client.headers["X-Case-Secret"] = created["secret"]
    saved = []
    monkeypatch.setattr(get_store(), "save_evidence", lambda *args: saved.append(args))
    response = client.post(f"/cases/{created['id']}/evidence",
        files={"files": ("large.txt", b"x" * (7 * 1024 * 1024 + 1), "text/plain")})
    assert response.status_code == 413
    assert saved == []


def test_language_switch_requires_owner_and_preserves_completed_steps(client):
    case = client.post("/cases", json={"country": "IN", "language": "en"}).json()
    base = f"/cases/{case['id']}"
    assert client.put(base + "/language", json={"language": "hi"}).status_code == 403
    client.headers["X-Case-Secret"] = case["secret"]
    completed = client.post(base + "/steps", json={"step_id": "call_helpline"}).json()
    result = client.put(base + "/language", json={"language": "hi"})
    assert result.status_code == 200
    translated = result.json()
    assert translated["language"] == "hi"
    old = next(s for s in completed["steps"] if s["id"] == "call_helpline")
    new = next(s for s in translated["steps"] if s["id"] == "call_helpline")
    assert new["done"] and new["done_at"] == old["done_at"]
    assert new["label"] != old["label"]
    assert client.put(base + "/language", json={"language": "id"}).status_code == 422


def test_slow_extraction_does_not_block_live_websocket(client, monkeypatch):
    import threading
    import time
    from app import main
    started, release = threading.Event(), threading.Event()
    def slow_extract(case, payload):
        started.set()
        release.wait(timeout=3)
        return case, []
    async def fake_live(ws, case_id, language):
        await ws.accept()
        await ws.send_json({"type": "ready"})
        await ws.close()
    monkeypatch.setattr(main.extract_svc, "extract", slow_extract)
    monkeypatch.setattr(main, "live_session", fake_live)
    with client:
        case = client.post("/cases", json={}).json()
        client.headers["X-Case-Secret"] = case["secret"]
        result = []
        thread = threading.Thread(target=lambda: result.append(client.post(
            f"/cases/{case['id']}/evidence", files={"files": ("x.txt", b"synthetic", "text/plain")})))
        thread.start()
        try:
            assert started.wait(timeout=2)
            before = time.monotonic()
            with client.websocket_connect(f"/live/{case['id']}?secret={case['secret']}") as socket:
                assert socket.receive_json() == {"type": "ready"}
            assert time.monotonic() - before < 1.5
        finally:
            release.set()
            thread.join(timeout=5)
        assert result[0].status_code == 200
