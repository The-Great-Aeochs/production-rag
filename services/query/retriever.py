"""Hybrid retrieval: Qdrant semantic search + Postgres BM25 keyword search.

Results are merged via Reciprocal Rank Fusion (RRF) to combine the
strengths of both approaches — semantic catches meaning, keyword
catches exact names and terms.
"""

import logging

import psycopg
from qdrant_client import QdrantClient

from shared.config import settings
from shared.models import RetrievalResult

log = logging.getLogger(__name__)


def semantic_search(
    query_embedding: list[float],
    qdrant: QdrantClient,
    filters: dict | None = None,
    top_k: int = 30,
) -> list[RetrievalResult]:
    """Vector similarity search in Qdrant."""
    from qdrant_client.models import (
        FieldCondition,
        Filter,
        MatchValue,
        QuantizationSearchParams,
        SearchParams,
    )

    query_filter = None
    if filters:
        conditions = [
            FieldCondition(key=k, match=MatchValue(value=v))
            for k, v in filters.items()
        ]
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

    return [
        RetrievalResult(
            chunk_id=str(point.id),
            content=point.payload.get("content", ""),
            source_path=point.payload.get("source_path", ""),
            section_path=point.payload.get("section_path", []),
            score=point.score,
            retrieval_method="semantic",
        )
        for point in results.points
    ]


def keyword_search(
    query: str,
    conn: psycopg.Connection,
    filters: dict | None = None,
    top_k: int = 30,
) -> list[RetrievalResult]:
    """Full-text search in Postgres using tsvector."""
    # Build the tsquery from the user's query
    where_clauses = ["search_vector @@ websearch_to_tsquery('english', %(query)s)"]
    params: dict = {"query": query, "limit": top_k}

    if filters:
        if "doc_type" in filters:
            where_clauses.append("doc_type = %(doc_type)s")
            params["doc_type"] = filters["doc_type"]
        if "language" in filters:
            where_clauses.append("language = %(language)s")
            params["language"] = filters["language"]

    where = " AND ".join(where_clauses)
    sql = f"""
        SELECT chunk_id, content, source_path, section_path,
               ts_rank_cd(search_vector, websearch_to_tsquery('english', %(query)s)) AS score
        FROM chunks
        WHERE {where}
        ORDER BY score DESC
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
            if result.chunk_id not in best_result or result.score > best_result[result.chunk_id].score:
                best_result[result.chunk_id] = result

    # Sort by RRF score descending
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)

    return [
        best_result[chunk_id].model_copy(
            update={"score": rrf_score, "retrieval_method": "hybrid"}
        )
        for chunk_id, rrf_score in ranked
    ]
