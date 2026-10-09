"""Test fixture: load synthetic cases (data-gen/out/cases.json) into the store.

Cases are re-timed relative to 'now' so the golden-hour clock looks live in the console.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.models import Case, Stage
from app.store import get_store
from app.services.extract import transaction_fields
from app.tools.validators import validate_case

log = logging.getLogger(__name__)


def load_seed(path: str) -> int:
    p = Path(path)
    if not p.is_absolute():
        p = (Path(__file__).resolve().parent.parent / path).resolve()
    if not p.exists():
        log.info("No seed file at %s - console starts empty", p)
        return 0
    data = json.loads(p.read_text(encoding="utf-8"))
    now = datetime.now(timezone.utc)
    store = get_store()
    n = 0
    prepared = []
    for item in data["cases"]:
        minutes_ago = item.pop("_minutes_ago", None)
        case = Case.model_validate(item["case"])
        if case.id == "GH-CASE-SUNITA":
            continue  # The hero must be created live by the victim upload, never pre-seeded.
        # Manually prepared synthetic seed values are user-entered, not OCR-checked claims.
        for t in case.transactions:
            for _, obj, name in transaction_fields(t):
                field = getattr(obj, name)
                field.status = "user" if field.value else "missing"
                field.source_file = "user"
            t.confirmed = True
        validate_case(case)
        if minutes_ago is not None:
            first = case.first_txn_time()
            if first:
                shift = (now - timedelta(minutes=minutes_ago)) - first
                for t in case.transactions:
                    if t.timestamp.value:
                        dt = datetime.fromisoformat(t.timestamp.value) + shift
                        t.timestamp.value = dt.isoformat()
                case.created_at = now - timedelta(minutes=max(minutes_ago - 5, 0))
        case.synthetic = True
        case.stage = Stage.FILING
        validate_case(case)
        prepared.append(case)
        n += 1
    store.put_many(prepared)
    log.info("Seeded %d synthetic cases", n)
    return n
