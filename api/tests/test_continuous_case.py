import json
from datetime import datetime, timedelta, timezone

from app.models import Beneficiary, Case, Field_, Rail, Transaction
from fixtures.seed import load_seed
from app.store import MemoryStore
from app.tools.linking import linked_count


def synthetic_case(case_id):
    def f(value):
        return Field_(value=value)
    return Case(id=case_id, synthetic=True, transactions=[Transaction(rail=Rail.UPI,
        utr=f("123456789012"), amount=f("10000"),
        timestamp=f((datetime.now(timezone.utc) - timedelta(days=2)).isoformat()),
        beneficiary=Beneficiary(vpa=f("rbi.verify.cell@oksbi")))])


def test_seed_excludes_hero_and_has_six_validated_recent_peers(tmp_path, monkeypatch):
    from app import store
    monkeypatch.setattr(store, "_store", MemoryStore())
    cases = [synthetic_case("GH-CASE-SUNITA")] + [synthetic_case(f"GH-PEER-{i}") for i in range(6)]
    path = tmp_path / "seed.json"
    path.write_text(json.dumps({"cases": [{"case": c.model_dump(mode="json"), "_minutes_ago": 15} for c in cases]}))
    assert load_seed(str(path)) == 6
    assert store.get_store().get("GH-CASE-SUNITA") is None
    peers = store.get_store().list()
    assert all(c.transactions[0].beneficiary.vpa.valid for c in peers)
    assert all(abs((datetime.now(timezone.utc) - c.first_txn_time()).total_seconds() / 60 - 15) < .1 for c in peers)
    created_live = synthetic_case("GH-LIVE-NEW")
    created_live.transactions[0].beneficiary.vpa = Field_(value="rbi.verify.cell@oksbi", valid=True, status="checked")
    assert linked_count(created_live, peers + [created_live]) == 6
