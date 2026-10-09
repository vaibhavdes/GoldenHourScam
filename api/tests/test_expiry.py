from datetime import timedelta
import pytest

from app.config import Settings
from app.models import Case, now
from app.store import MemoryStore


def test_expired_case_cannot_be_read_or_listed():
    store = MemoryStore()
    expired = Case(expires_at=now() - timedelta(seconds=1))
    live = Case()
    store.put(expired)
    store.put(live)
    assert store.get(expired.id) is None
    assert [c.id for c in store.list()] == [live.id]


def test_production_rejects_wildcard_cors():
    with pytest.raises(ValueError, match="explicit allowed origins"):
        Settings(store_backend="firestore", cors_origins="*")
