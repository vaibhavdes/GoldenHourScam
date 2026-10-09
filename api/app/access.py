"""Anonymous case capabilities and private responder access."""
import hashlib
import json
import re
import secrets

from fastapi import Header, HTTPException

from app.config import get_settings
from app.models import Case
from app.store import get_store


def secret_hash(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def owns_case(case: Case | None, secret: str | None) -> bool:
    return bool(case and case.secret_hash and secret and
                secrets.compare_digest(case.secret_hash, secret_hash(secret)))


def require_case(case_id: str, x_case_secret: str | None = Header(default=None)):
    if not can_access_case(get_store().get(case_id), x_case_secret):
        if get_settings().open_workspace:
            raise HTTPException(404, "This report is unavailable in this browser or has expired. Open Your reports or start a new report.")
        raise HTTPException(403, "Case secret required. Open this case in the browser where you created it.")


def require_console(x_console_key: str | None = Header(default=None)):
    if get_settings().open_workspace:
        return
    expected = get_settings().console_key
    if not expected or not x_console_key or not secrets.compare_digest(expected, x_console_key):
        raise HTTPException(403, "Responder access key required")


def can_access_case(case: Case | None, secret: str | None) -> bool:
    return owns_case(case, secret)


def case_view(case: Case) -> dict:
    return case.model_dump(mode="json", exclude={"expires_at": True, "secret_hash": True, "revision": True, "audit": True, "evidence_text": True,
                                                 "evidence": {"__all__": {"uri"}}})


def workspace_cases(x_case_capabilities: str | None = Header(default=None)) -> list[Case]:
    """Only browser-owned cases; no anonymous access to another person's reports."""
    if not get_settings().open_workspace:
        return get_store().list()
    if not x_case_capabilities:
        return []
    try:
        if len(x_case_capabilities) > 8192:
            raise ValueError()
        capabilities = json.loads(x_case_capabilities)
        if not isinstance(capabilities, dict) or len(capabilities) > 50:
            raise ValueError()
        if any(not isinstance(k, str) or not isinstance(v, str) or len(k) > 80 or len(v) > 100 or not re.fullmatch(r"[A-Za-z0-9_-]+", k)
               for k, v in capabilities.items()):
            raise ValueError()
    except (ValueError, TypeError):
        raise HTTPException(400, "Invalid browser report access") from None
    cases = []
    for case_id, secret in capabilities.items():
        case = get_store().get(case_id)
        if owns_case(case, secret):
            cases.append(case)
    return cases
