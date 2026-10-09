from types import SimpleNamespace

from app.models import Case
from app.services import followup


def test_task_client_failure_is_visible_and_does_not_block_case(monkeypatch):
    from google.cloud import tasks_v2
    monkeypatch.setattr(followup, "get_settings", lambda: SimpleNamespace(
        tasks_queue="projects/test-project/locations/us-central1/queues/reminders", public_base_url="https://service.example.test", tasks_service_account="tasks@test-project.iam.gserviceaccount.com"))
    def unavailable():
        raise RuntimeError("credentials unavailable")
    monkeypatch.setattr(tasks_v2, "CloudTasksClient", unavailable)
    case = Case(country="IN")
    result = followup.schedule(case)
    assert all(item["schedule_status"] == "failed" and not item["delivery_active"] for item in result)
    assert all(item["schedule_status"] == "failed" for item in followup.reminders(case))


def test_success_and_duplicate_tasks_are_scheduled_without_delivery_claim(monkeypatch):
    from google.api_core.exceptions import AlreadyExists
    from google.cloud import tasks_v2
    monkeypatch.setattr(followup, "get_settings", lambda: SimpleNamespace(
        tasks_queue="projects/test-project/locations/us-central1/queues/reminders", public_base_url="https://service.example.test", tasks_service_account="tasks@test-project.iam.gserviceaccount.com"))
    names = set()
    def create_task(**kwargs):
        request = kwargs["task"]["http_request"]
        assert request["oidc_token"] == {"service_account_email": "tasks@test-project.iam.gserviceaccount.com", "audience": "https://service.example.test"}
        name = kwargs["task"]["name"]
        if name in names:
            raise AlreadyExists("already scheduled")
        names.add(name)
    monkeypatch.setattr(tasks_v2, "CloudTasksClient", lambda: SimpleNamespace(create_task=create_task))
    case = Case(country="IN", language="hi")
    for _ in range(2):
        result = followup.schedule(case)
        assert all(item["schedule_status"] == "scheduled" and not item["delivery_active"] for item in result)
    assert len(names) == 3
    assert "बैंक" in result[1]["text"]
