"""GoldenHour API (Cloud Run)."""
from __future__ import annotations

import logging
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, FastAPI, File, Form, Header, HTTPException, UploadFile, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.access import case_view, can_access_case, require_case, require_console, secret_hash, workspace_cases
from app.config import get_settings
from app.live.proxy import live_session
from app.models import (AckReq, Case, ConfirmReq, CreateCaseReq, FilingPack, HoldRequest,
                        Field_, PrecheckReq, PrecheckResp, ScamType, Stage, StepReq)
from app.packs import available_packs, load_pack
from app.services import classify as classify_svc
from app.services import extract as extract_svc
from app.services import filing, followup, lockdown, responder
from app.share import make_token, read_token
from app.store import audit, get_store, set_step
from app.tools.dlp import safe_console_view, safe_helper_text
from app.tools.linking import identifiers
from app.tools.score import score_case
from app.tools.validators import validate_case

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("goldenhour")

ALLOWED_MIME = {"image/png", "image/jpeg", "image/webp", "image/heic",
                "application/pdf", "text/plain"}
MAX_FILES = 10


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield


app = FastAPI(title="GoldenHour API", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=get_settings().cors_origins.split(","),
                   allow_methods=["GET", "POST", "PUT", "OPTIONS"],
                   allow_headers=["Content-Type", "X-Case-Secret", "X-Console-Key", "X-Case-Capabilities"])
case_router = APIRouter(dependencies=[Depends(require_case)])
console_router = APIRouter(dependencies=[Depends(require_console)])


def _case(case_id: str) -> Case:
    c = get_store().get(case_id)
    if c is None:
        raise HTTPException(404, "Case not found")
    return c


def _console_case(case_id: str, cases: list[Case]) -> Case:
    case = next((c for c in cases if c.id == case_id), None)
    if case is None:
        raise HTTPException(404, "Report not found in this workspace")
    return case


# ---------------------------------------------------------------- meta
@app.get("/health")
def health():
    s = get_settings()
    return {"ok": True, "store": s.store_backend, "models": {"main": s.model_main,
            "lite": s.model_lite, "live": s.model_live}}


@app.get("/packs")
def packs():
    return available_packs()


@app.get("/experience")
def experience():
    return {"open_workspace": get_settings().open_workspace, "case_access": "browser_owned"}


@app.get("/patterns")
def patterns():
    from app.patterns import PATTERNS
    return PATTERNS


# ---------------------------------------------------------------- victim flow
@app.post("/cases")
def create_case(req: CreateCaseReq):
    load_pack(req.country)  # validates country
    case = Case(country=req.country.upper(), language=req.language,
                victim_name=req.victim_name, victim_age=req.victim_age, synthetic=False)
    secret = secrets.token_urlsafe(24)
    case.secret_hash = secret_hash(secret)
    lockdown.ensure_steps(case)
    audit(case, "victim", "case_created")
    get_store().put(case)
    return case_view(case) | {"secret": secret}


@case_router.get("/cases/{case_id}")
def get_case(case_id: str):
    return case_view(_case(case_id))


class LanguageReq(BaseModel):
    language: Literal["en", "hi", "ms"]


@case_router.put("/cases/{case_id}/language")
def case_language(case_id: str, req: LanguageReq):
    case = _case(case_id)
    case.language = req.language
    previous = {step.id: step for step in case.steps}
    case.steps = []
    lockdown.ensure_steps(case)
    for item in case.steps:
        if item.id in previous:
            item.done, item.done_at = previous[item.id].done, previous[item.id].done_at
    if case.transactions:
        scam_type, confidence = case.scam_type, case.scam_type_confidence
        classify_svc.classify(case, case.timeline, case.explanation or "")
        # Changing the display language must not change the incident category.
        case.scam_type, case.scam_type_confidence = scam_type, confidence
    get_store().put(case)
    return case_view(case)


class TransferTimeReq(BaseModel):
    timestamp: datetime


@case_router.put("/cases/{case_id}/transfer-time")
def transfer_time(case_id: str, req: TransferTimeReq):
    if req.timestamp.tzinfo is None or req.timestamp > datetime.now(timezone.utc):
        raise HTTPException(400, "Use a past transfer time with a timezone")
    case = _case(case_id)
    case.reported_transfer_time = Field_(value=req.timestamp.isoformat(), status="user", valid=True,
                                         confidence=1, source_file="user")
    audit(case, "victim", "transfer_time_entered")
    get_store().put(case)
    return case_view(case)


class ExtractResp(BaseModel):
    case: dict
    timeline: list[dict]


@case_router.post("/cases/{case_id}/evidence", response_model=ExtractResp)
async def upload_evidence(case_id: str, files: list[UploadFile] = File(...),
                          notes: str = Form(default="", max_length=10000)):
    case = _case(case_id)
    if not files or len(files) > MAX_FILES:
        raise HTTPException(400, f"Upload at most {MAX_FILES} files at a time")
    max_bytes = min(load_pack(case.country)["portal"]["evidence_max_mb"], 7) * 1024 * 1024
    store = get_store()
    payload = []
    validated = []
    for i, f in enumerate(files, 1):
        data = await f.read(max_bytes + 1)
        mime = (f.content_type or "application/octet-stream").split(";")[0]
        if mime not in ALLOWED_MIME:
            raise HTTPException(415, f"{f.filename}: unsupported type {mime}")
        if len(data) > max_bytes:
            raise HTTPException(413, f"{f.filename}: file too large")
        if not data:
            raise HTTPException(400, f"{f.filename}: empty file")
        validated.append((f.filename or f"file{i}", mime, data))
    # Validate the whole request before uploading anything to persistent storage.
    for filename, mime, data in validated:
        ev = await run_in_threadpool(store.save_evidence, case.id, filename, mime, data)
        case.evidence.append(ev)
        payload.append((f"{ev.id} {ev.filename}", mime, data))

    # Gemini/GCS clients are synchronous. Keep long uploads off the Live WebSocket loop.
    try:
        case, timeline = await run_in_threadpool(extract_svc.extract, case, payload)
    except Exception as error:
        log.warning("Evidence extraction unavailable: %s", type(error).__name__)
        await run_in_threadpool(store.put, case)
        raise HTTPException(503, "Reading evidence is unavailable right now. Your files were saved. Retry or enter the transfer details manually; call the helpline and bank immediately.") from None
    case.timeline = (case.timeline or []) + timeline
    if case.transactions or case.suspects or notes:
        case = await run_in_threadpool(classify_svc.classify, case, case.timeline, notes)
        lockdown.refresh_lockdown(case)
    for s in case.steps:
        if s.id == "evidence":
            s.done, s.done_at = True, datetime.now(timezone.utc)
    case.stage = Stage.FILING
    audit(case, "system", f"extracted {len(case.transactions)} transactions from {len(files)} files")
    await run_in_threadpool(store.put, case)
    return ExtractResp(case=case_view(case), timeline=timeline)


@case_router.put("/cases/{case_id}/confirm")
def confirm(case_id: str, req: ConfirmReq):
    """User-edited/confirmed transactions. Edited values are user-asserted (quote = value)."""
    case = _case(case_id)
    from app.services.extract import transaction_fields
    existing = {t.id: t for t in case.transactions}
    for t in req.transactions:
        old = existing.get(t.id)
        for path, obj, name in transaction_fields(t):
            field = getattr(obj, name)
            old_obj = old.beneficiary if old and path.startswith("beneficiary.") else old
            previous = getattr(old_obj, name) if old_obj else None
            edited = (not previous or field.value != previous.value or
                      (field.status == "user" and field.source_quote is None))
            if edited:
                field.status = "user" if field.value else "missing"
                field.source_quote, field.source_file = None, "user"
                field.issue, field.valid, field.confidence = None, False, 1.0
            else:
                setattr(obj, name, previous.model_copy(deep=True))
        t.confirmed = True
    case.transactions = req.transactions
    case.suspects = req.suspects
    validate_case(case)
    audit(case, "victim", "confirmed_details")
    get_store().put(case)
    return case_view(case)


@case_router.post("/cases/{case_id}/steps")
def step(case_id: str, req: StepReq):
    case = _case(case_id)
    set_step(case, req.step_id, req.done, "victim")
    get_store().put(case)
    return case_view(case)


@case_router.post("/cases/{case_id}/ack")
def ack(case_id: str, req: AckReq):
    case = _case(case_id)
    case.ack_number = req.ack_number.strip()
    case.reported_at = case.reported_at or datetime.now(timezone.utc)
    case.stage = Stage.TRACKING
    audit(case, "victim", "ack_number_added")
    scheduled = followup.schedule(case)
    get_store().put(case)
    return {"case": case_view(case), "reminders": scheduled}


@case_router.get("/cases/{case_id}/pack", response_model=FilingPack)
def pack(case_id: str):
    case = _case(case_id)
    return filing.build_pack(case, case.timeline)


@case_router.get("/cases/{case_id}/restoration")
def restoration(case_id: str):
    return {"restoration_request": filing.build_restoration(_case(case_id))}


@case_router.get("/cases/{case_id}/reminders")
def reminders(case_id: str):
    return followup.reminders(_case(case_id))


@case_router.post("/cases/{case_id}/share")
def share(case_id: str):
    _case(case_id)
    return {"token": make_token(case_id), "expires_hours": 24}


@app.get("/shared/{token}")
def shared(token: str):
    case_id = read_token(token)
    if not case_id:
        raise HTTPException(403, "Link expired or invalid")
    c = _case(case_id)
    reviewed = filing.reviewed_case(c)
    return {
        "case_id": c.id, "country": c.country, "scam_type": c.scam_type.value,
        "explanation": safe_helper_text(c, c.explanation or ""),
        "steps": [s.model_dump() for s in c.steps],
        "transactions": [{"amount": t.amount.value, "time": t.timestamp.value,
                          "reference": (t.utr.value[:4] + "****" + t.utr.value[-4:]) if t.utr.value else None}
                         for t in reviewed.transactions],
        "helplines": load_pack(c.country)["helplines"],
    }


@app.post("/precheck", response_model=PrecheckResp)
def precheck(req: PrecheckReq):
    try:
        return classify_svc.precheck(req.text, req.country, req.language)
    except Exception as error:
        code = getattr(error, "code", None)
        log.warning("AI precheck unavailable: %s; upstream_status=%s", type(error).__name__, code if isinstance(code, int) else None)
        raise HTTPException(503, "AI check is unavailable right now. Do not pay or share passwords; verify through an official number you already know.") from None


@app.post("/recovery-check", response_model=PrecheckResp)
def recovery_check(req: PrecheckReq):
    r = precheck(req.model_copy(update={"text": "Someone is offering to recover my lost money: " + req.text}))
    if r.verdict != "likely_scam" and any(k in req.text.lower() for k in
                                          ("fee", "charge", "advance", "processing", "hacker", "seed phrase")):
        r.verdict, r.scam_type = "likely_scam", ScamType.RECOVERY
    return r


@app.websocket("/live/{case_id}")
async def live(ws: WebSocket, case_id: str, lang: Literal["en", "hi", "ms"] = "en", secret: str = ""):
    if not can_access_case(get_store().get(case_id), secret):
        await ws.close(code=1008, reason="Report unavailable in this browser")
        return
    await live_session(ws, case_id, lang)


# ---------------------------------------------------------------- responder console
@console_router.get("/console/queue")
def console_queue(country: str | None = None, cases: list[Case] = Depends(workspace_cases)):
    if country:
        cases = [c for c in cases if c.country == country.upper()]
    return responder.queue(cases, include_empty=get_settings().open_workspace)


@console_router.get("/console/cases/{case_id}")
def console_case(case_id: str, explain: bool = True, cases: list[Case] = Depends(workspace_cases)):
    c = _console_case(case_id, cases)
    from app.tools.linking import linked_count
    card = score_case(c, linked_cases=linked_count(c, cases))
    if explain:
        card.explanation = responder.explain(card)
    view = safe_console_view(c, case_view(c))
    mine = identifiers(c)
    linked = [{"case_id": o.id, "shared": sorted(mine & identifiers(o)), "total_lost": o.total_lost()}
              for o in cases if o.id != c.id and o.country == c.country and mine & identifiers(o)]
    return {"case": view, "score": card, "linked_cases": linked}


class HoldReq(BaseModel):
    model_config = {"extra": "forbid"}
    txn_id: str | None = None


@console_router.post("/console/cases/{case_id}/hold-request", response_model=HoldRequest)
def console_hold(case_id: str, req: HoldReq, cases: list[Case] = Depends(workspace_cases)):
    return responder.hold_request(_console_case(case_id, cases), cases, req.txn_id)


@console_router.get("/console/clusters")
def console_clusters(cases: list[Case] = Depends(workspace_cases)):
    return responder.clusters(cases)


class AttributionReq(BaseModel):
    case_ids: list[str] = Field(min_length=1, max_length=500)
    held_amount: float = Field(ge=0, allow_inf_nan=False)


@console_router.post("/console/clusters/attribution")
def console_attribution(req: AttributionReq, cases: list[Case] = Depends(workspace_cases)):
    return responder.cluster_attribution(cases, req.case_ids, req.held_amount)


def require_task_identity(authorization: str | None = Header(default=None)):
    s = get_settings()
    if not s.tasks_service_account or not s.public_base_url or not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(403, "Task identity required")
    from google.auth.transport.requests import Request
    from google.oauth2 import id_token
    try:
        claims = id_token.verify_oauth2_token(authorization[7:], Request(), audience=s.public_base_url)
    except Exception:
        raise HTTPException(403, "Invalid task identity") from None
    if claims.get("email") != s.tasks_service_account or claims.get("email_verified") is not True:
        raise HTTPException(403, "Invalid task identity")


@app.post("/internal/reminders/{case_id}", dependencies=[Depends(require_task_identity)])
def reminder_hook(case_id: str):
    """Target of Cloud Tasks. Delivery (push/SMS/WhatsApp) is a roadmap item; logged for now."""
    log.info("Reminder due for case %s", case_id)
    return {"ok": True}


app.include_router(case_router)
app.include_router(console_router)
