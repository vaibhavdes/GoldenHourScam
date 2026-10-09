from datetime import datetime
from types import SimpleNamespace

from app.models import Case
from app.store import FirestoreStore


def test_seed_batches_respect_write_limit_and_preserve_native_ttl():
    batches = []
    def make_batch():
        writes = []
        committed = []
        batch = SimpleNamespace(set=lambda reference, data: writes.append((reference, data)),
                                commit=lambda: committed.append(True))
        batches.append((writes, committed))
        return batch
    store = FirestoreStore.__new__(FirestoreStore)
    store.db = SimpleNamespace(batch=make_batch)
    store.col = SimpleNamespace(document=lambda case_id: case_id)
    cases = [Case(id=f"GH-BATCH-{i}") for i in range(501)]
    store.put_many(cases)
    assert [len(writes) for writes, _ in batches] == [500, 1]
    assert all(committed == [True] for _, committed in batches)
    assert all(isinstance(data["expires_at"], datetime) for writes, _ in batches for _, data in writes)
