from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from services.query import pipeline
from services.query.cache import get_cached, query_key, set_cached
from services.query.generator import PROMPT_VERSION
from services.query.session import create_session
from shared.config import settings
from shared.models import QueryRequest, QueryResponse


def key(req=None, owner="owner", revision=1, prompt=PROMPT_VERSION):
    return query_key(req or QueryRequest(query="Foo"), owner, revision, prompt)


@pytest.mark.parametrize(
    "req",
    [
        QueryRequest(query="foo"),
        QueryRequest(query="Foo "),
        QueryRequest(query="Foo", top_k=2),
        QueryRequest(query="Foo", filters={"doc_type": "code"}),
        QueryRequest(query="Foo", filters={"source_path": "private.py"}),
        QueryRequest(query="Foo", filters={"corpus_id": "other"}),
    ],
)
def test_cache_parameters_cannot_collide(req):
    assert key(req) != key()


def test_cache_is_partitioned_by_identity_revision_and_versions(monkeypatch):
    original = key()
    assert key(owner="other") != original
    assert key(revision=2) != original
    assert key(prompt="v2") != original
    monkeypatch.setattr(settings, "ollama_model", "different-model")
    assert key() != original


def test_filter_order_is_canonical():
    assert key(QueryRequest(query="q", filters={"doc_type": "code", "language": "python"})) == key(
        QueryRequest(query="q", filters={"language": "python", "doc_type": "code"})
    )


def test_cache_does_not_persist_session_or_timings(redis_client):
    set_cached(
        "test",
        QueryResponse(answer="yes", session_id="secret", latency_ms={"total": 5}),
        redis_client,
    )
    cached = get_cached("test", redis_client)
    assert cached.session_id is None
    assert cached.latency_ms == {}


def test_cache_hit_skips_embedding(monkeypatch, pool, redis_client):
    req = QueryRequest(query="Foo")
    set_cached(key(owner="local"), QueryResponse(answer="cached"), redis_client)
    embed = Mock(side_effect=AssertionError("embedding should not run"))
    monkeypatch.setattr(pipeline, "embed_query", embed)
    result = pipeline.run_query(req, pool, Mock(), redis_client)
    assert result.cached and result.answer == "cached"
    embed.assert_not_called()


def test_cache_disabled_means_no_read_or_write(monkeypatch, pool, redis_client, chunk):
    monkeypatch.setattr(pipeline, "embed_query", lambda _: [1.0])
    monkeypatch.setattr(pipeline, "retrieve_and_rerank", lambda *_: [chunk])
    monkeypatch.setattr(pipeline, "generate", lambda *_: "answer")
    cache_read, cache_write = Mock(), Mock()
    monkeypatch.setattr(pipeline, "get_cached", cache_read)
    monkeypatch.setattr(pipeline, "set_cached", cache_write)
    pipeline.run_query(QueryRequest(query="q", use_cache=False), pool, Mock(), redis_client)
    cache_read.assert_not_called()
    cache_write.assert_not_called()


def test_conversation_cache_is_never_shared(monkeypatch, pool, redis_client, chunk):
    sid = create_session(redis_client, "owner")
    monkeypatch.setattr(pipeline, "embed_query", lambda _: [1.0])
    monkeypatch.setattr(pipeline, "retrieve_and_rerank", lambda *_: [chunk])
    monkeypatch.setattr(pipeline, "generate", lambda *_: "answer")
    cache_read, cache_write = Mock(), Mock()
    monkeypatch.setattr(pipeline, "get_cached", cache_read)
    monkeypatch.setattr(pipeline, "set_cached", cache_write)
    result = pipeline.run_query(
        QueryRequest(query="q", session_id=sid), pool, Mock(), redis_client, "owner"
    )
    assert result.session_id == sid
    cache_read.assert_not_called()
    cache_write.assert_not_called()


def test_foreign_session_is_denied_before_retrieval(pool, redis_client):
    sid = create_session(redis_client, "owner")
    with pytest.raises(HTTPException) as exc:
        pipeline.prepare_query(
            QueryRequest(query="q", session_id=sid), pool, Mock(), redis_client, "attacker"
        )
    assert exc.value.status_code == 404


def test_revision_authority_failure_disables_cache(monkeypatch, pool, redis_client, chunk):
    pool.conn.execute.side_effect = RuntimeError("database unavailable")
    monkeypatch.setattr(pipeline, "embed_query", lambda _: [1.0])
    monkeypatch.setattr(pipeline, "retrieve_and_rerank", lambda *_: [chunk])
    read = Mock()
    monkeypatch.setattr(pipeline, "get_cached", read)
    state = pipeline.prepare_query(QueryRequest(query="q"), pool, Mock(), redis_client)
    assert state.cache_key is None
    read.assert_not_called()


def test_total_retrieval_outage_is_not_a_no_results_answer(monkeypatch):
    monkeypatch.setattr(pipeline, "_semantic", Mock(side_effect=ConnectionError))
    monkeypatch.setattr(pipeline, "_keyword", Mock(side_effect=ConnectionError))
    with pytest.raises(HTTPException) as exc:
        pipeline._parallel_retrieve([], "q", Mock(), Mock(), None)
    assert exc.value.status_code == 503


def test_one_failed_retrieval_leg_degrades(monkeypatch, chunk):
    monkeypatch.setattr(pipeline, "_semantic", Mock(side_effect=ConnectionError))
    monkeypatch.setattr(pipeline, "_keyword", lambda *_: [chunk])
    semantic, keyword = pipeline._parallel_retrieve([], "q", Mock(), Mock(), None)
    assert semantic == [] and keyword == [chunk]


def test_session_queries_are_serialized_and_release_on_error(
    monkeypatch, pool, redis_client, chunk
):
    from services.query.session import get_recent_messages

    sid = create_session(redis_client, "owner")
    req = QueryRequest(query="q", session_id=sid)
    monkeypatch.setattr(pipeline, "embed_query", lambda _: [1.0])
    monkeypatch.setattr(pipeline, "retrieve_and_rerank", lambda *_: [chunk])
    first = pipeline.prepare_query(req, pool, Mock(), redis_client, "owner")
    with pytest.raises(HTTPException) as exc:
        pipeline.prepare_query(req, pool, Mock(), redis_client, "owner")
    assert exc.value.status_code == 409
    pipeline.release_query(first)
    monkeypatch.setattr(pipeline, "generate", Mock(side_effect=RuntimeError("failed")))
    with pytest.raises(RuntimeError):
        pipeline.run_query(req, pool, Mock(), redis_client, "owner")
    assert get_recent_messages(sid, redis_client) == []
    # A failed generation cannot strand the session lock.
    next_query = pipeline.prepare_query(req, pool, Mock(), redis_client, "owner")
    pipeline.release_query(next_query)


def test_expired_session_lease_cannot_append_late_messages(monkeypatch, pool, redis_client, chunk):
    from services.query.session import get_recent_messages

    sid = create_session(redis_client, "owner")
    monkeypatch.setattr(pipeline, "embed_query", lambda _: [1.0])
    monkeypatch.setattr(pipeline, "retrieve_and_rerank", lambda *_: [chunk])
    state = pipeline.prepare_query(
        QueryRequest(query="q", session_id=sid), pool, Mock(), redis_client, "owner"
    )
    redis_client.delete(f"session:{sid}:lock")
    redis_client.set(f"session:{sid}:lock", "new-query-token")
    with pytest.raises(HTTPException) as exc:
        pipeline.complete_query(state, "stale answer", pool, redis_client)
    assert exc.value.status_code == 409
    assert get_recent_messages(sid, redis_client) == []
    pipeline.release_query(state)
    assert redis_client.get(f"session:{sid}:lock") == "new-query-token"


def test_retrieval_work_remains_bounded_after_caller_times_out(monkeypatch):
    from threading import BoundedSemaphore, Event

    finished = Event()
    monkeypatch.setattr(pipeline, "_RETRIEVAL_SLOTS", BoundedSemaphore(1))
    future = pipeline._submit(lambda: finished.wait(2))
    try:
        assert pipeline._submit(lambda: []) is None
    finally:
        finished.set()
        future.result(timeout=3)
