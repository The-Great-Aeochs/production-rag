"""Query pipeline orchestrator.

Wires together: session → rewrite → cache → embed → retrieve → rerank → generate.
Retrieval runs the semantic and keyword legs in parallel, each with a timeout
budget; if a leg fails or times out the pipeline degrades to the other leg's
results rather than blocking.

Multi-turn flow:
- If session_id is provided, load conversation history from Redis
- Rewrite the query using history context (coreference resolution)
- Use the rewritten query for retrieval + generation
- Save user message + assistant response back to session
"""

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError

import redis
from psycopg_pool import ConnectionPool
from qdrant_client import QdrantClient

from shared.config import settings
from shared.models import ConversationMessage, QueryRequest, QueryResponse, RetrievalResult
from services.ingestion.embedder import embed_query
from services.query.cache import get_cached, set_cached
from services.query.generator import PROMPT_VERSION, generate
from services.query.reranker import rerank
from services.query.retriever import keyword_search, reciprocal_rank_fusion, semantic_search
from services.query.rewriter import rewrite_query
from services.query.session import (
    add_message,
    create_session,
    get_recent_messages,
    get_summary,
    session_exists,
)

log = logging.getLogger(__name__)

# Shared pool for running the two retrieval legs concurrently. Sized to cover
# several in-flight queries (2 legs each) without unbounded thread growth.
_RETRIEVAL_POOL = ThreadPoolExecutor(max_workers=16, thread_name_prefix="retrieval")


def _count_tokens_approx(text: str) -> int:
    """Fast approximate token count (1 token ~ 4 chars)."""
    return len(text) // 4


def run_query(
    request: QueryRequest,
    pool: ConnectionPool,
    qdrant: QdrantClient,
    redis_client: redis.Redis,
) -> QueryResponse:
    """Execute the full query pipeline synchronously."""
    timings: dict[str, float] = {}
    total_start = time.time()

    # 0. Session handling: load history + rewrite query
    session_id = request.session_id
    history: list[ConversationMessage] = []
    summary: str | None = None
    search_query = request.query  # default: use raw query

    if session_id:
        t = time.time()
        if not session_exists(session_id, redis_client):
            session_id = create_session(redis_client)

        history = _safe_load_history(session_id, redis_client)
        summary = _safe_load_summary(session_id, redis_client)
        timings["session_load"] = _ms(t)

        # Rewrite query using conversation context
        if history:
            t = time.time()
            search_query = _safe_rewrite(request.query, history, summary)
            timings["rewrite"] = _ms(t)
            if search_query != request.query:
                log.info(f"Rewrote query: '{request.query}' -> '{search_query}'")

        # Save the user message to session
        _safe_add_message(session_id, ConversationMessage(
            role="user",
            content=request.query,
            token_count=_count_tokens_approx(request.query),
        ), redis_client)

    # 1. Embed the (possibly rewritten) query
    t = time.time()
    query_embedding = embed_query(search_query)
    timings["embed"] = _ms(t)

    # 2. Check cache (keyed on the rewritten query text)
    if request.use_cache:
        t = time.time()
        cached = _safe_cache_get(search_query, redis_client)
        timings["cache_check"] = _ms(t)
        if cached is not None:
            cached.cached = True
            cached.session_id = session_id
            cached.latency_ms = timings
            # Still save the assistant response to session
            if session_id:
                _safe_add_message(session_id, ConversationMessage(
                    role="assistant",
                    content=cached.answer,
                    token_count=_count_tokens_approx(cached.answer),
                ), redis_client)
            return cached

    # 3. Hybrid retrieval (parallel) + 4. rerank
    t = time.time()
    top_chunks = retrieve_and_rerank(
        search_query, query_embedding, pool, qdrant, request.filters, request.top_k
    )
    timings["retrieval"] = _ms(t)

    if not top_chunks:
        no_result = QueryResponse(
            answer="I couldn't find any relevant information to answer your question.",
            session_id=session_id,
            latency_ms=timings,
            model_used=settings.ollama_model,
            prompt_version=PROMPT_VERSION,
        )
        if session_id:
            _safe_add_message(session_id, ConversationMessage(
                role="assistant",
                content=no_result.answer,
                token_count=_count_tokens_approx(no_result.answer),
            ), redis_client)
        return no_result

    # 5. Generate (pass conversation history for context)
    t = time.time()
    answer = generate(
        search_query,
        top_chunks,
        history=history if session_id else None,
        summary=summary,
    )
    timings["generation"] = _ms(t)

    timings["total"] = _ms(total_start)

    response = QueryResponse(
        answer=answer,
        sources=top_chunks,
        cached=False,
        session_id=session_id,
        latency_ms=timings,
        model_used=settings.ollama_model,
        prompt_version=PROMPT_VERSION,
    )

    # 6. Save assistant response to session
    if session_id:
        _safe_add_message(session_id, ConversationMessage(
            role="assistant",
            content=answer,
            token_count=_count_tokens_approx(answer),
        ), redis_client)

    # 7. Cache the response (keyed on the rewritten query text, best-effort)
    _safe_cache_set(search_query, response, redis_client)

    # 8. Log query (best-effort)
    _safe_log_query(request, top_chunks, response, pool)

    return response


def retrieve_and_rerank(
    search_query: str,
    query_embedding: list[float],
    pool: ConnectionPool,
    qdrant: QdrantClient,
    filters: dict | None,
    top_k: int,
) -> list[RetrievalResult]:
    """Parallel hybrid retrieval (semantic + keyword) → RRF merge → rerank.

    Shared by the blocking and streaming query paths. Each retrieval leg runs
    with its own timeout budget; a slow or failing leg degrades to the other.
    Returns the reranked top-k chunks (possibly empty).
    """
    semantic_results, keyword_results = _parallel_retrieve(
        query_embedding, search_query, pool, qdrant, filters
    )

    merged = reciprocal_rank_fusion(semantic_results, keyword_results)
    log.info(
        f"Retrieved {len(semantic_results)} semantic + {len(keyword_results)} keyword "
        f"= {len(merged)} merged"
    )

    if not merged:
        return []

    return _safe_rerank(search_query, merged, top_k)


def _parallel_retrieve(
    embedding: list[float],
    query: str,
    pool: ConnectionPool,
    qdrant: QdrantClient,
    filters: dict | None,
) -> tuple[list[RetrievalResult], list[RetrievalResult]]:
    """Run both retrieval legs concurrently, each bounded by a timeout."""
    semantic_future = _RETRIEVAL_POOL.submit(_safe_semantic, embedding, qdrant, filters)
    keyword_future = _RETRIEVAL_POOL.submit(_safe_keyword, query, pool, filters)

    semantic_results = _await_leg(semantic_future, "semantic")
    keyword_results = _await_leg(keyword_future, "keyword")
    return semantic_results, keyword_results


def _await_leg(future, name: str) -> list[RetrievalResult]:
    try:
        return future.result(timeout=settings.retrieval_timeout_s)
    except FutureTimeoutError:
        log.warning(f"{name} retrieval timed out after {settings.retrieval_timeout_s}s")
        return []
    except Exception as e:
        log.warning(f"{name} retrieval failed: {e}")
        return []


def _safe_load_history(
    session_id: str, client: redis.Redis
) -> list[ConversationMessage]:
    try:
        return get_recent_messages(session_id, client)
    except Exception as e:
        log.warning(f"Session history load failed: {e}")
        return []


def _safe_load_summary(session_id: str, client: redis.Redis) -> str | None:
    try:
        return get_summary(session_id, client)
    except Exception as e:
        log.warning(f"Session summary load failed: {e}")
        return None


def _safe_rewrite(
    query: str,
    history: list[ConversationMessage],
    summary: str | None,
) -> str:
    try:
        return rewrite_query(query, history, summary)
    except Exception as e:
        log.warning(f"Query rewrite failed, using original: {e}")
        return query


def _safe_add_message(
    session_id: str, message: ConversationMessage, client: redis.Redis
) -> None:
    try:
        add_message(session_id, message, client)
    except Exception as e:
        log.warning(f"Session message save failed: {e}")


def _safe_semantic(
    embedding: list[float], qdrant: QdrantClient, filters: dict | None
) -> list[RetrievalResult]:
    try:
        return semantic_search(embedding, qdrant, filters)
    except Exception as e:
        log.warning(f"Semantic search failed: {e}")
        return []


def _safe_keyword(
    query: str, pool: ConnectionPool, filters: dict | None
) -> list[RetrievalResult]:
    # Uses its own pooled connection so a slow query holds (and eventually
    # releases) a dedicated connection rather than the request's.
    try:
        with pool.connection() as conn:
            return keyword_search(query, conn, filters)
    except Exception as e:
        log.warning(f"Keyword search failed: {e}")
        return []


def _safe_rerank(
    query: str, results: list[RetrievalResult], top_k: int
) -> list[RetrievalResult]:
    try:
        return rerank(query, results, top_k)
    except Exception as e:
        log.warning(f"Reranker failed, using RRF order: {e}")
        return results[:top_k]


def _safe_cache_get(query: str, client: redis.Redis) -> QueryResponse | None:
    try:
        return get_cached(query, client)
    except Exception as e:
        log.warning(f"Cache read failed: {e}")
        return None


def _safe_cache_set(query: str, response: QueryResponse, client: redis.Redis) -> None:
    try:
        set_cached(query, response, client)
    except Exception as e:
        log.warning(f"Cache write failed: {e}")


def _safe_log_query(
    request: QueryRequest,
    chunks: list[RetrievalResult],
    response: QueryResponse,
    pool: ConnectionPool,
) -> None:
    try:
        with pool.connection() as conn:
            conn.execute(
                """
                INSERT INTO query_logs (query_text, filters, retrieved_chunks, answer,
                                        model_used, prompt_version, latency_ms, cache_hit)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    request.query,
                    json.dumps(request.filters) if request.filters else None,
                    json.dumps([{"chunk_id": c.chunk_id, "score": c.score, "method": c.retrieval_method} for c in chunks]),
                    response.answer,
                    response.model_used,
                    response.prompt_version,
                    json.dumps(response.latency_ms),
                    response.cached,
                ),
            )
    except Exception as e:
        log.warning(f"Query logging failed: {e}")


def _ms(start: float) -> float:
    return round((time.time() - start) * 1000, 1)
