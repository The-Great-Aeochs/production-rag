"""Hybrid retrieval: Qdrant semantic search + Postgres full-text keyword search.

Results are merged via Reciprocal Rank Fusion (RRF) to combine the
strengths of both approaches — semantic catches meaning, keyword
catches exact names and terms.
"""

import logging

import psycopg
from qdrant_client import QdrantClient

from shared.config import settings
from shared.db import get_pg_conn
from shared.filters import validate_filters
from shared.models import RetrievalResult

log = logging.getLogger(__name__)


def semantic_search(
    query_embedding: list[float],
    qdrant: QdrantClient,
    filters: dict | None = None,
    top_k: int = 30,
    conn: psycopg.Connection | None = None,
    pool=None,
) -> list[RetrievalResult]:
    """Vector similarity search in Qdrant."""
    from qdrant_client.models import (
        FieldCondition,
        Filter,
        MatchValue,
        QuantizationSearchParams,
        SearchParams,
    )

    filters = validate_filters(filters)
    filters.setdefault("corpus_id", settings.corpus_id)
    query_filter = None
    if filters:
        conditions = [FieldCondition(key=k, match=MatchValue(value=v)) for k, v in filters.items()]
        query_filter = Filter(must=conditions)

    # The collection stores INT8-quantized vectors. Rescore the top candidates
    # against the full-precision vectors to recover the recall lost to
    # quantization (oversampling fetches extra candidates before rescoring).
    search_params = SearchParams(
        quantization=QuantizationSearchParams(rescore=True, oversampling=2.0)
    )

    results = qdrant.query_points(
        collection_name=settings.qdrant_collection,
        query=query_embedding,
        query_filter=query_filter,
        limit=top_k,
        search_params=search_params,
    )

    # Qdrant payloads are candidates, never an authorization/content authority.
    # Deleted, pending, stale-version and foreign chunks must not reach generation.
    if pool is not None:
        with pool.connection() as pooled_conn:
            return hydrate_results(results.points, pooled_conn, filters)
    if conn is None:
        with get_pg_conn(autocommit=True) as owned_conn:
            return hydrate_results(results.points, owned_conn, filters)
    return hydrate_results(results.points, conn, filters)


def hydrate_results(points, conn, filters: dict[str, str]) -> list[RetrievalResult]:
    if not points:
        return []
    clauses, params = _filter_sql(filters)
    params["ids"] = [str(point.id) for point in points]
    rows = conn.execute(
        "SELECT c.chunk_id, c.content, c.source_path, c.section_path FROM chunks c "
        "JOIN documents d ON d.doc_id=c.doc_id WHERE d.sync_status='ready' "
        "AND c.chunk_id = ANY(%(ids)s) AND " + " AND ".join(clauses),
        params,
    ).fetchall()
    valid = {row[0]: row for row in rows}
    return [
        RetrievalResult(
            chunk_id=str(point.id),
            content=valid[str(point.id)][1],
            source_path=valid[str(point.id)][2],
            section_path=valid[str(point.id)][3] or [],
            score=point.score,
            retrieval_method="semantic",
        )
        for point in points
        if str(point.id) in valid
    ]


def _filter_sql(filters: dict[str, str] | None) -> tuple[list[str], dict]:
    filters = validate_filters(filters)
    filters.setdefault("corpus_id", settings.corpus_id)
    # Columns come exclusively from the shared allowlist; values are parameters.
    return ([f"c.{key} = %({key})s" for key in sorted(filters)], dict(filters))


def keyword_search(
    query: str,
    conn: psycopg.Connection,
    filters: dict | None = None,
    top_k: int = 30,
) -> list[RetrievalResult]:
    """Full-text search in Postgres using tsvector."""
    clauses, params = _filter_sql(filters)
    clauses.extend(
        ["d.sync_status = 'ready'", "search_vector @@ websearch_to_tsquery('english', %(query)s)"]
    )
    params.update(query=query, limit=top_k)
    where = " AND ".join(clauses)
    sql = f"""
        SELECT c.chunk_id, c.content, c.source_path, c.section_path,
               ts_rank_cd(search_vector, websearch_to_tsquery('english', %(query)s)) AS score
        FROM chunks c JOIN documents d ON d.doc_id=c.doc_id
        WHERE {where}
        ORDER BY score DESC, c.chunk_id
        LIMIT %(limit)s
    """

    rows = conn.execute(sql, params).fetchall()
    return [
        RetrievalResult(
            chunk_id=row[0],
            content=row[1],
            source_path=row[2],
            section_path=row[3] or [],
            score=float(row[4]),
            retrieval_method="keyword",
        )
        for row in rows
    ]


def reciprocal_rank_fusion(
    *result_lists: list[RetrievalResult],
    k: int = 60,
) -> list[RetrievalResult]:
    """Merge multiple ranked lists using RRF.

    score = sum(1 / (k + rank_i)) across all lists where the item appears.
    Higher k dampens the effect of high-ranking items.
    """
    scores: dict[str, float] = {}
    best_result: dict[str, RetrievalResult] = {}

    for results in result_lists:
        for rank, result in enumerate(results):
            rrf_score = 1.0 / (k + rank + 1)
            scores[result.chunk_id] = scores.get(result.chunk_id, 0.0) + rrf_score

            # Keep the result with the higher individual score
            if (
                result.chunk_id not in best_result
                or result.score > best_result[result.chunk_id].score
            ):
                best_result[result.chunk_id] = result

    # Sort by RRF score descending
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)

    return [
        best_result[chunk_id].model_copy(update={"score": rrf_score, "retrieval_method": "hybrid"})
        for chunk_id, rrf_score in ranked
    ]
