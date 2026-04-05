"""Query pipeline orchestrator.

Wires together: session → rewrite → cache → embed → retrieve → rerank → generate.
Each stage has a timeout budget. If a stage fails or times out,
the pipeline degrades gracefully.

Multi-turn flow:
- If session_id is provided, load conversation history from Redis
- Rewrite the query using history context (coreference resolution)
- Use the rewritten query for retrieval + generation
- Save user message + assistant response back to session
"""

import json
import logging
import time

import psycopg
import redis
from qdrant_client import QdrantClient

from shared.config import settings
from shared.models import ConversationMessage, QueryRequest, QueryResponse, RetrievalResult
from services.ingestion.embedder import embed_batch
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


def _count_tokens_approx(text: str) -> int:
    """Fast approximate token count (1 token ~ 4 chars)."""
    return len(text) // 4


def run_query(
    request: QueryRequest,
    conn: psycopg.Connection,
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
    elif session_id is None and request.session_id is None:
        # Single-turn mode, no session management
        pass

    # 1. Embed the (possibly rewritten) query
    t = time.time()
    query_embedding = embed_batch([search_query])[0]
    timings["embed"] = _ms(t)

    # 2. Check cache (using rewritten query embedding)
    if request.use_cache:
        t = time.time()
        cached = _safe_cache_get(query_embedding, redis_client)
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

    # 3. Hybrid retrieval (use rewritten query for both legs)
    t = time.time()
    semantic_results = _safe_semantic(query_embedding, qdrant, request.filters)
    keyword_results = _safe_keyword(search_query, conn, request.filters)
    timings["retrieval"] = _ms(t)

    merged = reciprocal_rank_fusion(semantic_results, keyword_results)
    log.info(
        f"Retrieved {len(semantic_results)} semantic + {len(keyword_results)} keyword "
        f"= {len(merged)} merged"
    )

    if not merged:
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

    # 4. Rerank
    t = time.time()
    top_chunks = _safe_rerank(search_query, merged, request.top_k)
    timings["rerank"] = _ms(t)

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

    # 7. Cache in background (best-effort)
    _safe_cache_set(query_embedding, response, redis_client)

    # 8. Log query (best-effort)
    _safe_log_query(request, top_chunks, response, conn)

    return response


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
    query: str, conn: psycopg.Connection, filters: dict | None
) -> list[RetrievalResult]:
    try:
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


def _safe_cache_get(
    embedding: list[float], client: redis.Redis
) -> QueryResponse | None:
    try:
        return get_cached(embedding, client)
    except Exception as e:
        log.warning(f"Cache read failed: {e}")
        return None


def _safe_cache_set(
    embedding: list[float], response: QueryResponse, client: redis.Redis
) -> None:
    try:
        set_cached(embedding, response, client)
    except Exception as e:
        log.warning(f"Cache write failed: {e}")


def _safe_log_query(
    request: QueryRequest,
    chunks: list[RetrievalResult],
    response: QueryResponse,
    conn: psycopg.Connection,
) -> None:
    try:
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
        conn.commit()
    except Exception as e:
        log.warning(f"Query logging failed: {e}")


def _ms(start: float) -> float:
    return round((time.time() - start) * 1000, 1)
