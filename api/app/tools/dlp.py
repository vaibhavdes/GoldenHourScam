"""Redact personal data before it reaches the responder console / analytics.

Uses Sensitive Data Protection (DLP API) when enabled, else a regex fallback.
Beneficiary identifiers are NOT redacted (responders need them); victim identifiers are.
"""
import re
from copy import deepcopy

from app.config import get_settings
from app.models import Case

INFO_TYPES = ["PHONE_NUMBER", "EMAIL_ADDRESS", "INDIA_AADHAAR_INDIVIDUAL",
              "INDIA_PAN_INDIVIDUAL", "PERSON_NAME", "CREDIT_CARD_NUMBER"]

_FALLBACK = [
    (re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b"), "[AADHAAR]"),
    (re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"), "[PAN]"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "[EMAIL]"),
    (re.compile(r"(\+?\d{1,3}[\s-]?)?\b[6-9]\d{9}\b"), "[PHONE]"),
]


def redact(text: str) -> str:
    if not text:
        return text
    s = get_settings()
    if s.use_dlp and s.gcp_project:
        try:
            from google.cloud import dlp_v2

            client = dlp_v2.DlpServiceClient()
            resp = client.deidentify_content(request={
                "parent": f"projects/{s.gcp_project}/locations/global",
                "inspect_config": {"info_types": [{"name": n} for n in INFO_TYPES]},
                "deidentify_config": {"info_type_transformations": {"transformations": [
                    {"primitive_transformation": {"replace_with_info_type_config": {}}}]}},
                "item": {"value": text},
            })
            return resp.item.value
        except Exception:  # noqa: BLE001 - fall back to regex, never block the flow
            pass
    out = text
    for pat, rep in _FALLBACK:
        out = pat.sub(rep, out)
    return out


def safe_helper_text(case: Case, text: str) -> str:
    """Remove known victim values before best-effort DLP, including its fallback."""
    values = {case.victim_name or ""} | {t.victim_account_masked.value or "" for t in case.transactions}
    for value in sorted(values, key=len, reverse=True):
        if value:
            text = re.sub(re.escape(value), "[VICTIM]", text, flags=re.IGNORECASE)
    return redact(text)


def safe_console_view(case: Case, view: dict) -> dict:
    """Allowlist responder facts; exclude all unreviewed free text and source metadata.

    Browser ownership is not an institutional staff authorization system. In particular,
    do not send names, victim accounts, chat text, source quotes or model explanations.
    Narrative text is omitted from this report summary.
    """
    allowed = {k: deepcopy(view[k]) for k in ("id", "country", "language", "stage", "created_at",
               "scam_type", "transactions", "synthetic") if k in view}
    allowed["victim_name"] = None
    # Report summaries omit narrative: probabilistic name detection is insufficient.
    # Institutional adapters can opt into safe_helper_text with their privacy policy.
    allowed["narrative"] = None
    for transaction in allowed.get("transactions", []):
        transaction.pop("victim_account_masked", None)
        for key in ("amount", "utr", "timestamp"):
            field = transaction[key]
            field.pop("source_quote", None)
            field.pop("source_file", None)
            field["issue"] = None
            if not field.get("valid"):
                field["value"] = None
        beneficiary = transaction["beneficiary"]
        beneficiary["name"] = {"value": None, "valid": False, "status": "missing"}
        for key in ("vpa", "account", "ifsc", "bank"):
            field = beneficiary[key]
            field.pop("source_quote", None)
            field.pop("source_file", None)
            field["issue"] = None
            if not field.get("valid"):
                field["value"] = None
    return allowed
