import asyncio
import json
import threading
from unittest.mock import Mock

import pytest

from services.api.routes import query
from services.query import pipeline
from services.query.generator import ThinkFilter
from shared.config import settings
from shared.models import QueryResponse

from .conftest import ADMIN, TOKEN_B


def test_protected_routes_require_authentication(client):
    assert client.post("/query", json={"query": "q"}).status_code == 401
    assert client.post("/session").status_code == 401
    assert client.post("/ingest", json={}).status_code == 401
    assert client.get("/metrics").status_code == 401
    assert client.get("/health/live").status_code == 200


def test_unconfigured_auth_fails_closed(client, monkeypatch, auth):
    monkeypatch.setattr(settings, "api_keys", {})
    assert client.post("/query", headers=auth, json={"query": "q"}).status_code == 503


@pytest.mark.parametrize(
    "payload",
    [
        {"query": ""},
        {"query": "   "},
        {"query": "a" * 4001},
        {"query": "q", "top_k": 0},
        {"query": "q", "top_k": 31},
        {"query": "q", "filters": {"unknown": "x"}},
        {"query": "q", "filters": {"doc_type": ["x"]}},
        {"query": "q", "session_id": "bad"},
        {"query": "q", "extra": True},
    ],
)
def test_request_bounds(client, auth, payload):
    assert client.post("/query", headers=auth, json=payload).status_code == 422


def test_cross_corpus_requests_are_rejected(client, auth):
    assert (
        client.post(
            "/query", headers=auth, json={"query": "q", "filters": {"corpus_id": "beta"}}
        ).status_code
        == 403
    )


def test_server_adds_authorization_filter(client, auth, monkeypatch):
    run = Mock(return_value=QueryResponse(answer="yes"))
    monkeypatch.setattr(query, "run_query", run)
    assert client.post("/query", headers=auth, json={"query": "q"}).status_code == 200
    assert run.call_args.args[0].filters == {"corpus_id": "alpha"}


def test_foreign_session_is_not_accessible(client, auth):
    sid = client.post("/session", headers=auth).json()["session_id"]
    response = client.post(
        "/query",
        headers={"Authorization": f"Bearer {TOKEN_B}"},
        json={"query": "q", "session_id": sid},
    )
    assert response.status_code == 404


def test_rate_limit_uses_redis_atomic_counter(client, auth, monkeypatch):
    monkeypatch.setattr(settings, "requests_per_minute", 2)
    assert client.post("/session", headers=auth).status_code == 201
    assert client.post("/session", headers=auth).status_code == 201
    assert client.post("/session", headers=auth).status_code == 429


def test_query_token_cannot_access_admin_routes(client, auth):
    assert client.post("/ingest", headers=auth, json={}).status_code == 403


def test_body_limit_checks_actual_bytes_without_content_length(client, auth, monkeypatch):
    monkeypatch.setattr(settings, "max_request_bytes", 1024)
    response = client.post("/query", headers=auth, content=iter([b"x" * 600, b"y" * 600]))
    assert response.status_code == 413
    assert len(response.headers["x-request-id"]) == 32


def test_dependency_health_does_not_restart_process(client):
    client.app.state.models_ready = False
    assert client.get("/health/live").status_code == 200
    assert client.get("/health/ready").status_code == 503


def test_metrics_are_protected_and_have_bounded_labels(client):
    response = client.get("/metrics", headers={"Authorization": f"Bearer {ADMIN}"})
    assert response.status_code == 200
    assert "rag_http_requests_total" in response.text


def events(response):
    return [
        json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")
    ]


def test_stream_preparation_uses_worker_thread_and_shared_completion(
    client, auth, monkeypatch, chunk
):
    seen = []
    original_prepare = pipeline.prepare_query

    def prepare(*args):
        seen.append(threading.current_thread().name)
        return original_prepare(*args)

    monkeypatch.setattr(query, "prepare_query", prepare)
    monkeypatch.setattr(pipeline, "embed_query", lambda _: [1.0])
    monkeypatch.setattr(pipeline, "retrieve_and_rerank", lambda *_: [chunk])

    async def tokens(*args):
        await asyncio.sleep(0)
        yield "answer"

    monkeypatch.setattr(query, "generate_stream", tokens)
    response = client.post("/query/stream", headers=auth, json={"query": "q"})
    data = events(response)
    assert response.status_code == 200
    assert data[-1] == {"done": True}
    assert data[1]["token"] == "answer"
    assert "worker" in seen[0].lower()
    # The shared completion populates the same cache read by the regular route.
    result = client.post("/query", headers=auth, json={"query": "q"}).json()
    assert result["cached"] and result["answer"] == "answer"


def test_broken_stream_emits_error_and_is_not_cached(
    client, auth, monkeypatch, chunk, redis_client
):
    monkeypatch.setattr(pipeline, "embed_query", lambda _: [1.0])
    monkeypatch.setattr(pipeline, "retrieve_and_rerank", lambda *_: [chunk])

    async def tokens(*args):
        yield "partial"
        raise RuntimeError("secret diagnostic")

    monkeypatch.setattr(query, "generate_stream", tokens)
    data = events(client.post("/query/stream", headers=auth, json={"query": "q"}))
    assert "error" in data[-1] and data[-1]["done"]
    assert "secret" not in str(data)
    assert not redis_client.keys("rag:cache:*")


@pytest.mark.parametrize("split", range(1, 8))
def test_think_tags_do_not_leak_when_split_at_any_boundary(split):
    text = "hello<think>secret thoughts</think>world"
    sanitizer = ThinkFilter()
    output = "".join(sanitizer.feed(text[i : i + split]) for i in range(0, len(text), split))
    assert output + sanitizer.finish() == "helloworld"


def test_stream_disconnect_releases_admission_even_if_headers_fail(monkeypatch, pool, redis_client):
    from types import SimpleNamespace

    from shared.models import QueryRequest
    from shared.security import Principal

    slots = threading.BoundedSemaphore(1)
    monkeypatch.setattr(query, "_slots", slots)
    state = pipeline.PreparedQuery(request=QueryRequest(query="q"), search_query="q")
    monkeypatch.setattr(query, "prepare_query", lambda *_: state)
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(pg_pool=pool, redis=redis_client, qdrant=Mock()))
    )
    response = query.query_stream_endpoint(
        QueryRequest(query="q"), request, Principal("owner", "alpha")
    )

    async def send(message):
        raise OSError("client disconnected")

    async def receive():
        return {"type": "http.disconnect"}

    from starlette.requests import ClientDisconnect

    async def invoke():
        with pytest.raises(ClientDisconnect):
            await response({"type": "http", "asgi": {"spec_version": "2.4"}}, receive, send)

    asyncio.run(invoke())
    assert slots.acquire(blocking=False)
    slots.release()


def test_reassigning_a_token_to_another_corpus_revokes_old_sessions(client, auth, monkeypatch):
    from .conftest import TOKEN_A

    sid = client.post("/session", headers=auth).json()["session_id"]
    monkeypatch.setattr(settings, "api_keys", {TOKEN_A: "beta"})
    response = client.post("/query", headers=auth, json={"query": "q", "session_id": sid})
    assert response.status_code == 404
