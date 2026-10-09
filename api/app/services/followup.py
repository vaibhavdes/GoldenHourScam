"""FollowUp: schedule the '24h to complete your portal complaint' reminder via Cloud Tasks.

Local development: reminders are computed and returned so the UI can show them (no task created).
Delivery channel (push/SMS) is a roadmap item; the task hits /internal/reminders/{case_id}.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from app.config import get_settings
from app.models import Case
from app.packs import load_pack

log = logging.getLogger(__name__)


def reminders(case: Case) -> list[dict]:
    pack = load_pack(case.country)
    hours = pack["portal"]["followup_hours"]
    base = case.reported_at or case.created_at
    deadline = base + timedelta(hours=hours)
    items = [
        {"id": "portal_deadline", "due_at": deadline.isoformat(),
         "remind_at": (deadline - timedelta(hours=4)).isoformat(),
         "text": pack.get("followup_note_hi", pack["portal"]["followup_note"]) if case.language == "hi" else pack["portal"]["followup_note"]},
        {"id": "bank_followup", "due_at": (base + timedelta(days=3)).isoformat(),
         "remind_at": (base + timedelta(days=3)).isoformat(),
         "text": "बैंक से विवाद और रोकी गई रकम की स्थिति पूछें।" if case.language == "hi" else "Ask your bank for the status of the dispute and any amount held."},
        {"id": "restoration", "due_at": (base + timedelta(days=7)).isoformat(),
         "remind_at": (base + timedelta(days=7)).isoformat(),
         "text": "धोखेबाज के खाते में रकम रोकी गई हो तो पावती या शिकायत संख्या से आधिकारिक पोर्टल पर रकम वापसी का अनुरोध करें।" if case.language == "hi" and case.country == "IN" else pack.get("restoration", {}).get("note", "")},
    ]
    for item in items:
        item["schedule_status"] = case.reminder_statuses.get(item["id"], "computed")
        item["delivery_active"] = False
    return items


def schedule(case: Case) -> list[dict]:
    items = reminders(case)
    s = get_settings()
    if not (s.tasks_queue and s.public_base_url):
        return items
    if not s.tasks_service_account:
        for item in items:
            item["schedule_status"] = "failed"
            case.reminder_statuses[item["id"]] = "failed"
        return items
    from google.api_core.exceptions import AlreadyExists
    from google.cloud import tasks_v2
    from google.protobuf import timestamp_pb2

    try:
        client = tasks_v2.CloudTasksClient()
    except Exception as error:
        log.warning("Reminder client unavailable: %s", type(error).__name__)
        for item in items:
            item["schedule_status"] = "failed"
            case.reminder_statuses[item["id"]] = "failed"
        return items
    for r in items:
        try:
            ts = timestamp_pb2.Timestamp()
            due = datetime.fromisoformat(r["remind_at"]).astimezone(timezone.utc)
            ts.FromDatetime(max(due, datetime.now(timezone.utc)))
            client.create_task(parent=s.tasks_queue, task={
                "name": f"{s.tasks_queue}/tasks/gh-{case.id}-{r['id']}",
                "http_request": {
                    "http_method": tasks_v2.HttpMethod.POST,
                    "url": f"{s.public_base_url}/internal/reminders/{case.id}",
                    "headers": {"Content-Type": "application/json"},
                    "body": json.dumps({"reminder_id": r["id"]}).encode(),
                    "oidc_token": {"service_account_email": s.tasks_service_account,
                                   "audience": s.public_base_url},
                },
                "schedule_time": ts,
            })
            r["schedule_status"] = "scheduled"
        except AlreadyExists:
            r["schedule_status"] = "scheduled"
        except Exception as error:
            r["schedule_status"] = "failed"
            log.warning("Reminder scheduling failed: %s", type(error).__name__)
        case.reminder_statuses[r["id"]] = r["schedule_status"]
    return items
