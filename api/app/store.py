"""Case + evidence persistence. Firestore/GCS in cloud, in-memory for local development."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from threading import RLock
from typing import Protocol
from fastapi import HTTPException

from app.config import get_settings
from app.models import AuditEntry, Case, Evidence, now


class Store(Protocol):
    def get(self, case_id: str) -> Case | None: ...
    def put(self, case: Case) -> Case: ...
    def put_many(self, cases: list[Case]) -> None: ...
    def list(self, limit: int = 500) -> list[Case]: ...
    def save_evidence(self, case_id: str, filename: str, mime: str, data: bytes) -> Evidence: ...
    def load_evidence(self, ev: Evidence) -> bytes: ...


class MemoryStore:
    def __init__(self) -> None:
        self._cases: dict[str, Case] = {}
        self._blobs: dict[str, bytes] = {}
        self._lock = RLock()

    def get(self, case_id):
        c = self._cases.get(case_id)
        return c.model_copy(deep=True) if c and c.expires_at > now() else None

    def put(self, case):
        with self._lock:
            existing = self._cases.get(case.id)
            if existing and existing.revision != case.revision:
                raise HTTPException(409, "Case changed in another request. Refresh and try again.")
            case.revision += 1
            self._cases[case.id] = case.model_copy(deep=True)
        return case

    def put_many(self, cases):
        for case in cases:
            self.put(case)

    def list(self, limit=500):
        return [c.model_copy(deep=True) for c in list(self._cases.values()) if c.expires_at > now()][:limit]

    def save_evidence(self, case_id, filename, mime, data):
        sha = hashlib.sha256(data).hexdigest()
        uri = f"mem://{case_id}/{sha[:16]}"
        self._blobs[uri] = data
        return Evidence(filename=filename, mime=mime, size_bytes=len(data), sha256=sha, uri=uri)

    def load_evidence(self, ev):
        return self._blobs[ev.uri]


class FirestoreStore:
    def __init__(self) -> None:
        from google.cloud import firestore, storage

        s = get_settings()
        self.db = firestore.Client(project=s.gcp_project or None)
        self.col = self.db.collection(s.case_collection)
        self.bucket = storage.Client(project=s.gcp_project or None).bucket(s.evidence_bucket)

    def get(self, case_id):
        snap = self.col.document(case_id).get()
        case = Case.model_validate(snap.to_dict()) if snap.exists else None
        return case if case and case.expires_at > now() else None

    def put(self, case):
        from google.cloud import firestore
        data = json.loads(case.model_dump_json())
        data["expires_at"] = case.expires_at  # Firestore TTL requires a native timestamp, not an ISO string.
        data["revision"] = case.revision + 1
        ref = self.col.document(case.id)

        @firestore.transactional
        def save(transaction):
            snap = ref.get(transaction=transaction)
            if snap.exists and (snap.to_dict() or {}).get("revision", 0) != case.revision:
                raise HTTPException(409, "Case changed in another request. Refresh and try again.")
            transaction.set(ref, data)

        save(self.db.transaction())
        case.revision = data["revision"]
        return case

    def put_many(self, cases):
        # Firestore batches are limited to 500 writes; seed without hundreds of round trips.
        for offset in range(0, len(cases), 500):
            batch = self.db.batch()
            for case in cases[offset:offset + 500]:
                data = json.loads(case.model_dump_json())
                data["expires_at"] = case.expires_at
                batch.set(self.col.document(case.id), data)
            batch.commit()

    def list(self, limit=500):
        return [c for d in self.col.limit(limit).stream() if (c := Case.model_validate(d.to_dict())).expires_at > now()]

    def save_evidence(self, case_id, filename, mime, data):
        sha = hashlib.sha256(data).hexdigest()
        prefix = "evidence"
        path = f"{prefix}/{case_id}/{sha[:16]}-{Path(filename).name}"
        blob = self.bucket.blob(path)
        blob.upload_from_string(data, content_type=mime)   # bucket has a 30-day lifecycle rule
        return Evidence(filename=filename, mime=mime, size_bytes=len(data), sha256=sha,
                        uri=f"gs://{self.bucket.name}/{path}")

    def load_evidence(self, ev):
        path = ev.uri.split("/", 3)[3]
        return self.bucket.blob(path).download_as_bytes()


_store: Store | None = None


def get_store() -> Store:
    global _store
    if _store is None:
        _store = FirestoreStore() if get_settings().store_backend == "firestore" else MemoryStore()
    return _store


def audit(case: Case, actor: str, action: str) -> None:
    case.audit.append(AuditEntry(actor=actor, action=action))


def set_step(case: Case, step_id: str, done: bool, actor: str) -> None:
    item = next((s for s in case.steps if s.id == step_id), None)
    if item is None:
        raise HTTPException(422, "Unknown checklist step")
    item.done = done
    item.done_at = (item.done_at or now()) if done else None
    if step_id == "call_helpline" and done and not case.reported_at:
        case.reported_at = now()
    audit(case, actor, f"step {step_id}={done}")
