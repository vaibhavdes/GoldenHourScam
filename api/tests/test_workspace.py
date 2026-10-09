import json
import pytest
from fastapi import HTTPException
from app.config import Settings, get_settings
from fixtures.examples import SCENARIOS, make_example, receipt
from app.models import Case
from app.store import get_store
from app.services.filing import build_fields
from app.services.responder import hold_request
from test_api import client


def enable(monkeypatch):
    monkeypatch.setenv("OPEN_WORKSPACE", "true")
    monkeypatch.setenv("CASE_COLLECTION", "cases")
    get_settings.cache_clear()


def owned_sample(client, kind):
    created = client.post("/cases", json={"country": "IN"}).json()
    original = get_store().get(created["id"])
    case = make_example(kind)
    case.id, case.secret_hash = original.id, original.secret_hash
    case.revision = original.revision
    get_store().put(case)
    client.headers["X-Case-Secret"] = created["secret"]
    client.headers["X-Case-Capabilities"] = json.dumps({case.id: created["secret"]})
    return case


def test_browser_owned_workspace_never_opens_unowned_cases(client, monkeypatch):
    enable(monkeypatch)
    try:
        other = client.post("/cases", json={}).json()
        assert not other["synthetic"]
        assert client.get("/console/queue").json() == []
        assert client.get(f"/cases/{other['id']}").status_code == 404
        sample = owned_sample(client, "digital-arrest")
        assert [x["case_id"] for x in client.get("/console/queue").json()] == [sample.id]
        assert client.get(f"/cases/{sample.id}").status_code == 200
        assert "195,000" in client.get(f"/cases/{sample.id}/restoration").json()["restoration_request"]
        assert client.get(f"/cases/{other['id']}").status_code == 404
        assert client.get(f"/console/cases/{other['id']}").status_code == 404
        assert client.post(f"/console/cases/{other['id']}/hold-request", json={}).status_code == 404
        assert client.post("/console/clusters/attribution", json={"case_ids": [other["id"]], "held_amount": 0}).status_code == 404
        for path in ("/examples", "/examples/malaysia/receipt", "/console/registry"):
            assert client.get(path).status_code == 404
        assert client.post("/examples/malaysia/start").status_code == 404
        patterns = client.get("/patterns").json()
        assert len(patterns) == 8 and all(p["url"].startswith("https://") for p in patterns)
        assert client.get("/experience").json()["case_access"] == "browser_owned"
    finally:
        get_settings.cache_clear()


def test_reports_include_unfinished_upload_flow(client, monkeypatch):
    enable(monkeypatch)
    try:
        created = client.post("/cases", json={}).json()
        rows = client.get("/console/queue", headers={"X-Case-Capabilities": json.dumps({created["id"]: created["secret"]})}).json()
        assert len(rows) == 1 and rows[0]["case_id"] == created["id"]
        assert rows[0]["transactions"] == 0 and rows[0]["minutes_since_txn"] is None
    finally:
        get_settings.cache_clear()


def test_browser_capabilities_reject_invalid_and_excessive_input(client, monkeypatch):
    enable(monkeypatch)
    try:
        invalid = ["not-json", "[]", '{"x":1}', '{"x/nested":"s"}', '{"":"s"}', '{"..":"s"}', "x" * 8193,
                   json.dumps({str(i): "s" for i in range(51)})]
        for value in invalid:
            assert client.get("/console/queue", headers={"X-Case-Capabilities": value}).status_code == 400
        assert client.get("/console/queue", headers={"X-Case-Capabilities": '{"missing":"wrong"}'}).json() == []
    finally:
        get_settings.cache_clear()


def test_curated_scenarios_are_realistic_without_faking_source_checks():
    assert len(SCENARIOS) == 12
    for scenario in SCENARIOS:
        c = make_example(scenario["id"])
        assert c.synthetic and c.first_txn_time() is not None
        assert all(t.amount.valid and t.utr.valid and t.timestamp.valid for t in c.transactions)
        assert all(t.amount.status == "user" for t in c.transactions)
        assert "FICTIONAL SAMPLE ONLY" in receipt(scenario["id"])
        fields, missing = build_fields(c)
        if scenario["id"] == "masked-account":
            assert any(f["key"] == "suspect_account" and not f["ok"] for f in fields)
            with pytest.raises(HTTPException):
                hold_request(c, [c])
        else:
            assert all(f["ok"] for f in fields if f["required"]), (scenario["id"], missing)
    credit = make_example("incoming-credit")
    assert credit.total_lost() == 9000
    assert len(credit.transactions) == 2
    assert credit.transactions[1].direction == "credit"
    first = credit.first_txn_time()
    credit.transactions[1].timestamp.value = "2020-01-01T09:00:00+05:30"
    assert credit.first_txn_time() == first
    from app.tools.linking import identifiers
    assert "vpa:fictional.employer@samplebank" not in identifiers(credit)
    request = hold_request(credit, [credit])
    assert request.fields["total_disputed"] == 9000
    assert len(request.fields["transactions"]) == 1
    with pytest.raises(HTTPException):
        hold_request(credit, [credit], credit.transactions[1].id)


def test_pack_read_does_not_conflict_with_concurrent_acknowledgement(client, monkeypatch):
    from threading import Event, Thread
    enable(monkeypatch)
    entered, release = Event(), Event()
    def slow_wording(**kwargs):
        entered.set()
        assert release.wait(3)
        return ""
    monkeypatch.setattr("app.services.filing.generate_text", slow_wording)
    sample = owned_sample(client, "digital-arrest")
    responses = []
    worker = Thread(target=lambda: responses.append(client.get(f"/cases/{sample.id}/pack")))
    worker.start()
    try:
        assert entered.wait(3)
        saved = client.post(f"/cases/{sample.id}/ack", json={"ack_number": "FICTIONAL-CONCURRENT-ACK"})
        assert saved.status_code == 200
        revision = get_store().get(sample.id).revision
    finally:
        release.set(); worker.join(5); get_settings.cache_clear()
    assert not worker.is_alive()
    assert responses[0].status_code == 200
    assert responses[0].json()["ready"]
    current = get_store().get(sample.id)
    assert current.ack_number == "FICTIONAL-CONCURRENT-ACK"
    assert current.revision == revision


def test_language_change_keeps_incident_category_and_completed_steps(client, monkeypatch):
    enable(monkeypatch)
    sample = owned_sample(client, "shopping")
    sample.steps[0].done = True
    get_store().put(sample)
    response = client.put(f"/cases/{sample.id}/language", json={"language": "hi"})
    assert response.status_code == 200
    translated = response.json()
    assert translated["language"] == "hi"
    assert translated["scam_type"] == "shopping"
    assert translated["steps"][0]["done"]
    assert translated["transactions"][0]["amount"]["value"] == "6500"
    get_settings.cache_clear()
