"""Domain models shared across services."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


def now() -> datetime:
    return datetime.now(timezone.utc)


class Rail(str, Enum):
    UPI = "UPI"
    IMPS = "IMPS"
    NEFT = "NEFT"
    RTGS = "RTGS"
    CARD = "CARD"
    WALLET = "WALLET"
    CRYPTO = "CRYPTO"
    GIFT_CARD = "GIFT_CARD"
    DUITNOW = "DUITNOW"
    PAYNOW = "PAYNOW"
    BANK_TRANSFER = "BANK_TRANSFER"
    UNKNOWN = "UNKNOWN"


class ScamType(str, Enum):
    INVESTMENT = "investment"
    DIGITAL_ARREST = "digital_arrest"
    TASK_JOB = "task_job"
    SEXTORTION = "sextortion"
    PHISHING_OTP = "phishing_otp"
    IMPERSONATION = "impersonation"
    SHOPPING = "shopping"
    RECOVERY = "recovery_scam"
    UNKNOWN = "unknown"


class Stage(str, Enum):
    PRECHECK = "precheck"
    SOS = "sos"
    FILING = "filing"
    TRACKING = "tracking"
    RESTORING = "restoring"
    CLOSED = "closed"


class Field_(BaseModel):
    """An extracted value with grounding."""
    value: Optional[str] = None
    confidence: float = 0.0
    source_quote: Optional[str] = None
    source_file: Optional[str] = None
    valid: bool = False
    issue: Optional[str] = None
    status: Literal["read", "checked", "user", "missing"] = "missing"


class Beneficiary(BaseModel):
    vpa: Field_ = Field_()
    account: Field_ = Field_()
    ifsc: Field_ = Field_()
    bank: Field_ = Field_()
    name: Field_ = Field_()


class Transaction(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex[:8])
    amount: Field_ = Field_()
    currency: str = "INR"
    rail: Rail = Rail.UNKNOWN
    utr: Field_ = Field_()
    timestamp: Field_ = Field_()           # ISO 8601 string
    victim_account_masked: Field_ = Field_()
    beneficiary: Beneficiary = Beneficiary()
    direction: Literal["debit", "credit"] = "debit"
    confirmed: bool = False


class Suspect(BaseModel):
    phone: Optional[str] = None
    url: Optional[str] = None
    handle: Optional[str] = None
    platform: Optional[str] = None
    claimed_identity: Optional[str] = None


class Evidence(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex[:10])
    filename: str
    mime: str
    size_bytes: int
    sha256: str
    uri: str                                # gs:// or mem://


class Step(BaseModel):
    id: str
    label: str
    done: bool = False
    done_at: Optional[datetime] = None


class AuditEntry(BaseModel):
    ts: datetime = Field(default_factory=now)
    actor: str
    action: str


class Case(BaseModel):
    id: str = Field(default_factory=lambda: "GH-" + uuid4().hex[:8].upper())
    country: str = "IN"
    language: str = "en"
    stage: Stage = Stage.SOS
    created_at: datetime = Field(default_factory=now)
    victim_name: Optional[str] = None
    victim_age: Optional[int] = None
    scam_type: ScamType = ScamType.UNKNOWN
    scam_type_confidence: float = 0.0
    red_flags: list[str] = []
    explanation: Optional[str] = None
    transactions: list[Transaction] = []
    suspects: list[Suspect] = []
    evidence: list[Evidence] = []
    steps: list[Step] = []
    ack_number: Optional[str] = None
    ncrp_complaint_id: Optional[str] = None
    reported_at: Optional[datetime] = None
    reported_transfer_time: Field_ = Field_()
    narrative: Optional[str] = None
    reminder_statuses: dict[str, str] = {}
    timeline: list[dict] = []
    synthetic: bool = False
    audit: list[AuditEntry] = []

    expires_at: datetime = Field(default_factory=lambda: now() + timedelta(days=30))
    secret_hash: str | None = None
    evidence_text: dict[str, str] = {}
    revision: int = 0                       # optimistic concurrency; never returned to browsers

    # convenience
    def first_txn_time(self) -> Optional[datetime]:
        times = []
        for t in self.transactions:
            if t.direction == "debit" and t.timestamp.value and t.timestamp.valid:
                try:
                    dt = datetime.fromisoformat(t.timestamp.value)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    times.append(dt)
                except ValueError:
                    pass
        if not times and self.reported_transfer_time.valid and self.reported_transfer_time.value:
            try:
                times.append(datetime.fromisoformat(self.reported_transfer_time.value))
            except ValueError:
                pass
        return min(times) if times else None

    def total_lost(self) -> float:
        total = 0.0
        for t in self.transactions:
            if t.direction == "debit" and t.amount.value and t.amount.valid:
                try:
                    total += float(t.amount.value)
                except ValueError:
                    pass
        return total


# ---------- API payloads ----------

class LocaleReq(BaseModel):
    country: Literal["IN", "MY", "SG"] = "IN"
    language: Literal["en", "hi", "ms"] = "en"

    @field_validator("country", mode="before")
    @classmethod
    def normalize_country(cls, value):
        return value.upper() if isinstance(value, str) else value


class CreateCaseReq(LocaleReq):
    victim_name: Optional[str] = Field(default=None, max_length=200)
    victim_age: Optional[int] = Field(default=None, ge=0, le=120)


class ConfirmReq(BaseModel):
    transactions: list[Transaction] = Field(max_length=100)
    suspects: list[Suspect] = Field(default_factory=list, max_length=100)


class StepReq(BaseModel):
    step_id: str = Field(min_length=1, max_length=64)
    done: bool = True


class AckReq(BaseModel):
    ack_number: str = Field(min_length=1, max_length=200)

    @field_validator("ack_number")
    @classmethod
    def nonempty_ack(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("Enter an acknowledgement number")
        return value


class PrecheckReq(LocaleReq):
    text: str = Field(min_length=1, max_length=10000)


class PrecheckResp(BaseModel):
    verdict: Literal["likely_scam", "suspicious", "unclear"]
    scam_type: ScamType
    red_flags: list[str]
    advice: str


class FilingPack(BaseModel):
    ready: bool
    country: str
    portal_name: str
    portal_url: str
    fields: list[dict]                      # [{label, value, required, ok, hint}]
    narrative: str
    narrative_ok: bool
    call_script: list[dict]                 # [{q, a}]
    bank_letter: str
    restoration_request: Optional[str] = None
    evidence_checklist: list[dict]
    missing: list[str]
    disclaimer: str


class ScoreFactor(BaseModel):
    name: str
    value: str
    weight: float
    contribution: float


class ScoreCard(BaseModel):
    case_id: str
    score: float
    minutes_since_txn: Optional[float]
    factors: list[ScoreFactor]
    explanation: Optional[str] = None


class HoldRequest(BaseModel):
    case_id: str
    action: Literal["HOLD_DISPUTED_AMOUNT"]
    text: str
    fields: dict
