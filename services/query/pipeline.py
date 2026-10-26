"""Shared preparation/completion for regular and streaming RAG requests."""

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from threading import BoundedSemaphore

import redis
from fastapi import HTTPException
from psycopg_pool import ConnectionPool
from qdrant_client import QdrantClient

from services.ingestion.embedder import embed_query
from services.query.cache import get_cached, query_key, set_cached
from services.query.generator import PROMPT_VERSION, generate
from services.query.reranker import rerank
from services.query.retriever import keyword_search, reciprocal_rank_fusion, semantic_search
from services.query.rewriter import rewrite_query
from services.query.session import append_turn, get_recent_messages, get_summary, session_owned_by
from shared.config import settings
from shared.models import ConversationMessage, QueryRequest, QueryResponse, RetrievalResult

log = logging.getLogger(__name__)
_RETRIEVAL_POOL = ThreadPoolExecutor(max_workers=16, thread_name_prefix="retrieval")
_RETRIEVAL_SLOTS = BoundedSemaphore(16)
NO_RESULTS = "I couldn't find any relevant information to answer your question."


@dataclass
class PreparedQuery:
    request: QueryRequest
    search_query: str
    owner: str = "local"
    session_lock: object = None
    history: list[ConversationMessage] = field(default_factory=list)
    summary: str | None = None
    chunks: list[RetrievalResult] = field(default_factory=list)
    cached: QueryResponse | None = None
    cache_key: str | None = None
    timings: dict[str, float] = field(default_factory=dict)
    started: float = field(default_factory=time.monotonic)


def prepare_query(
    request: QueryRequest, pool, qdrant, redis_client, owner: str = "local"
) -> PreparedQuery:
    state = PreparedQuery(request=request, search_query=request.query, owner=owner)
    try:
        return _prepare_query(state, pool, qdrant, redis_client)
    except BaseException:
        release_query(state)
        raise


def _prepare_query(state, pool, qdrant, redis_client):
    request, owner = state.request, state.owner
    if request.session_id:
        # Ownership checks fail closed; infrastructure failures must never bypass them.
        if not session_owned_by(request.session_id, owner, redis_client):
            raise HTTPException(404, "Session not found")
        state.session_lock = redis_client.lock(
            f"session:{request.session_id}:lock",
            thread_local=False,
            timeout=settings.generation_timeout_s + settings.rewrite_timeout_s + 30,
        )
        if not state.session_lock.acquire(blocking=False):
            state.session_lock = None
            raise HTTPException(409, "A query is already running for this session")
        state.history = get_recent_messages(request.session_id, redis_client)
        state.summary = get_summary(request.session_id, redis_client)
        try:
            state.search_query = rewrite_query(request.query, state.history, state.summary)
        except Exception:
            log.warning("Query rewrite failed; using original query")
    # History-dependent answers are not shared or cached. Revision lookup is also
    # required on cache reads: an unavailable authority must not serve stale data.
    if request.use_cache and not request.session_id:
        try:
            corpus = (request.filters or {}).get("corpus_id", settings.corpus_id)
            with pool.connection() as conn:
                row = conn.execute(
                    "SELECT revision FROM corpora WHERE corpus_id=%s", (corpus,)
                ).fetchone()
            state.cache_key = query_key(request, owner, row[0] if row else 0, PROMPT_VERSION)
            state.cached = get_cached(state.cache_key, redis_client)
        except Exception:
            state.cache_key = None
            log.warning("Cache unavailable; continuing without caching")
        if state.cached:
            state.cached = state.cached.model_copy(
                update={"cached": True, "latency_ms": {"total": _ms(state.started)}}
            )
            return state
    started = time.monotonic()
    embedding = embed_query(state.search_query)
    state.timings["embed"] = _ms(started)
    started = time.monotonic()
    state.chunks = retrieve_and_rerank(
        state.search_query,
        embedding,
        pool,
        qdrant,
        request.filters,
        request.top_k,
    )
    state.timings["retrieval"] = _ms(started)
    return state


def complete_query(state: PreparedQuery, answer: str, pool, redis_client) -> QueryResponse:
    state.timings["total"] = _ms(state.started)
    response = QueryResponse(
        answer=answer,
        sources=state.chunks,
        session_id=state.request.session_id,
        latency_ms=state.timings,
        model_used=settings.ollama_model,
        prompt_version=PROMPT_VERSION,
    )
    if state.request.session_id:
        if not append_turn(
            state.request.session_id,
            state.owner,
            state.session_lock.local.token,
            state.request.query,
            answer,
            redis_client,
        ):
            raise HTTPException(
                409, "Session expired or its query lease ended; retry in a new session"
            )
    if state.cache_key and state.chunks:
        try:
            set_cached(state.cache_key, response, redis_client)
        except Exception:
            log.warning("Cache write failed")
    _safe_log_query(state.request, state.chunks, response, pool)
    return response


def run_query(
    request: QueryRequest,
    pool: ConnectionPool,
    qdrant: QdrantClient,
    redis_client: redis.Redis,
    owner: str = "local",
) -> QueryResponse:
    state = prepare_query(request, pool, qdrant, redis_client, owner)
    try:
        if state.cached:
            return state.cached
        answer = NO_RESULTS
        if state.chunks:
            started = time.monotonic()
            answer = generate(state.search_query, state.chunks, state.history, state.summary)
            state.timings["generation"] = _ms(started)
        return complete_query(state, answer, pool, redis_client)
    finally:
        release_query(state)


def release_query(state):
    if state.session_lock is not None:
        try:
            state.session_lock.release()
        except redis.exceptions.LockError:
            pass  # Expired locks never authorize a late conversation write.
        except redis.RedisError:
            log.warning("Session lock release failed; it will expire")
        finally:
            state.session_lock = None


def retrieve_and_rerank(search_query, query_embedding, pool, qdrant, filters, top_k):
    semantic, keyword = _parallel_retrieve(query_embedding, search_query, pool, qdrant, filters)
    merged = reciprocal_rank_fusion(semantic, keyword)
    if not merged:
        return []
    try:
        return rerank(search_query, merged, top_k)
    except Exception:
        log.warning("Reranker failed; using fused retrieval order")
        return merged[:top_k]


def _parallel_retrieve(embedding, query, pool, qdrant, filters):
    futures = [
        _submit(_semantic, embedding, qdrant, pool, filters),
        _submit(_keyword, query, pool, filters),
    ]
    # A shared deadline prevents sequential waits from doubling the budget.
    done, pending = wait(
        [f for f in futures if f is not None], timeout=settings.retrieval_timeout_s
    )
    for future in pending:
        future.cancel()
    results = []
    failures = 0
    for future in futures:
        if future not in done:
            results.append([])
            failures += 1
            continue
        try:
            results.append(future.result())
        except Exception:
            log.warning("Retrieval dependency failed")
            results.append([])
            failures += 1
    if failures == 2:
        raise HTTPException(503, "Search is temporarily unavailable")
    return tuple(results)


def _submit(function, *args):
    # A timed-out caller cannot leave an unbounded queue of retrieval tasks.
    if not _RETRIEVAL_SLOTS.acquire(blocking=False):
        return None
    try:
        future = _RETRIEVAL_POOL.submit(function, *args)
    except BaseException:
        _RETRIEVAL_SLOTS.release()
        raise
    future.add_done_callback(lambda _: _RETRIEVAL_SLOTS.release())
    return future


def _semantic(embedding, qdrant, pool, filters):
    return semantic_search(embedding, qdrant, filters, pool=pool)


def _keyword(query, pool, filters):
    with pool.connection() as conn:
        return keyword_search(query, conn, filters)


def _safe_log_query(request, chunks, response, pool):
    try:
        with pool.connection() as conn:
            conn.execute(
                """INSERT INTO query_logs(query_text, filters, retrieved_chunks, answer,
                   model_used, prompt_version, latency_ms, cache_hit)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    request.query if settings.log_query_content else "[redacted]",
                    json.dumps(request.filters) if settings.log_query_content else None,
                    json.dumps([{"chunk_id": c.chunk_id, "score": c.score} for c in chunks]),
                    response.answer if settings.log_query_content else None,
                    response.model_used,
                    response.prompt_version,
                    json.dumps(response.latency_ms),
                    response.cached,
                ),
            )
    except Exception:
        log.warning("Query logging failed")


def _ms(start):
    return round((time.monotonic() - start) * 1000, 1)
