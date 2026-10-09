from types import SimpleNamespace
from unittest.mock import Mock
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import time

from app import llm


def test_both_model_backends_bound_calls_without_hidden_retries(monkeypatch):
    create = Mock()
    monkeypatch.setattr(llm.genai, "Client", create)
    try:
        for vertex in (True, False):
            llm.clear_client_cache()
            monkeypatch.setattr(llm, "get_settings", lambda: SimpleNamespace(use_vertex=vertex, gcp_project="test-project", gcp_location="us", gemini_api_key="test-only"))
            llm.client()
            options = create.call_args.kwargs["http_options"]
            assert options.timeout == 120_000
            assert options.retry_options.attempts == 1
    finally:
        llm.clear_client_cache()


def test_parallel_cold_requests_keep_one_live_client(monkeypatch):
    def construct(**kwargs):
        time.sleep(.02)  # SDK construction overlaps first requests.
        return object()
    create = Mock(side_effect=construct)
    monkeypatch.setattr(llm.genai, "Client", create)
    llm.clear_client_cache()
    start = Barrier(4)
    def request(_):
        start.wait(timeout=5)
        return llm.client()
    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            clients = list(pool.map(request, range(4)))
        assert create.call_count == 1
        assert all(c is clients[0] for c in clients)
    finally:
        llm.clear_client_cache()


def test_optional_ai_calls_have_shorter_bounds_than_evidence_reading(monkeypatch):
    generate = Mock(return_value=SimpleNamespace(text="{}"))
    monkeypatch.setattr(llm, "client", lambda: SimpleNamespace(models=SimpleNamespace(generate_content=generate)))
    from app.services.classify import _classification, precheck
    _classification("model", "English", {})
    config = generate.call_args.kwargs["config"]
    assert config.http_options.timeout == 45_000 < 120_000
    assert config.http_options.retry_options.attempts == 1
    precheck("An ordinary message", "IN", "en")
    assert generate.call_args.kwargs["config"].http_options.timeout == 30_000
    llm.generate_text(model="model", system="Draft", prompt="Reviewed facts")
    assert generate.call_args.kwargs["config"].http_options.timeout == 20_000
    llm.generate_json(model="model", system="Extract", parts=[])
    assert generate.call_args.kwargs["config"].http_options.timeout == 120_000
