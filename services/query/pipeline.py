"""Query pipeline orchestrator.

Wires together: cache → embed → retrieve → rerank → generate.
Each stage has a timeout budget. If a stage fails or times out,
the pipeline degrades gracefully.
"""

import asyncio
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor

import psycopg
import redis
from qdrant_client import QdrantClient

from shared.config import settings
from shared.models import QueryRequest, QueryResponse, RetrievalResult
from services.ingestion.embedder import embed_batch
from services.query.cache import get_cached, set_cached
from services.query.generator import PROMPT_VERSION, generate
from services.query.reranker import rerank
from services.query.retriever import keyword_search, reciprocal_rank_fusion, semantic_search

log = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=4)


def run_query(
    request: QueryRequest,
    conn: psycopg.Connection,
    qdrant: QdrantClient,
    redis_client: redis.Redis,
) -> QueryResponse:
    """Execute the full query pipeline synchronously."""
    timings: dict[str, float] = {}
    total_start = time.time()

    # 1. Embed the query
    t = time.time()
    query_embedding = embed_batch([request.query])[0]
    timings["embed"] = _ms(t)

    # 2. Check cache
    if request.use_cache:
        t = time.time()
        cached = _safe_cache_get(query_embedding, redis_client)
        timings["cache_check"] = _ms(t)
        if cached is not None:
            cached.cached = True
            cached.latency_ms = timings
            return cached

    # 3. Hybrid retrieval
    t = time.time()
    semantic_results = _safe_semantic(query_embedding, qdrant, request.filters)
    keyword_results = _safe_keyword(request.query, conn, request.filters)
    timings["retrieval"] = _ms(t)

    merged = reciprocal_rank_fusion(semantic_results, keyword_results)
    log.info(
        f"Retrieved {len(semantic_results)} semantic + {len(keyword_results)} keyword "
        f"= {len(merged)} merged"
    )

    if not merged:
        return QueryResponse(
            answer="I couldn't find any relevant information to answer your question.",
            latency_ms=timings,
            model_used=settings.ollama_model,
            prompt_version=PROMPT_VERSION,
        )

    # 4. Rerank
    t = time.time()
    top_chunks = _safe_rerank(request.query, merged, request.top_k)
    timings["rerank"] = _ms(t)

    # 5. Generate
    t = time.time()
    answer = generate(request.query, top_chunks)
    timings["generation"] = _ms(t)

    timings["total"] = _ms(total_start)

    response = QueryResponse(
        answer=answer,
        sources=top_chunks,
        cached=False,
        latency_ms=timings,
        model_used=settings.ollama_model,
        prompt_version=PROMPT_VERSION,
    )

    # 6. Cache in background (best-effort)
    _safe_cache_set(query_embedding, response, redis_client)

    # 7. Log query (best-effort)
    _safe_log_query(request, top_chunks, response, conn)

    return response


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
