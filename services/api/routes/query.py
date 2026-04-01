"""Query endpoints: full RAG pipeline and streaming."""

import json
import logging

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from shared.models import QueryRequest, QueryResponse
from services.ingestion.embedder import embed_batch
from services.query.cache import get_cached
from services.query.generator import generate_stream
from services.query.pipeline import run_query
from services.query.reranker import rerank
from services.query.retriever import keyword_search, reciprocal_rank_fusion, semantic_search

log = logging.getLogger(__name__)

router = APIRouter(tags=["query"])


@router.post("/query", response_model=QueryResponse)
def query_endpoint(req: QueryRequest, request: Request):
    """Full RAG pipeline: retrieve → rerank → generate."""
    return run_query(
        req,
        conn=request.app.state.pg_conn,
        qdrant=request.app.state.qdrant,
        redis_client=request.app.state.redis,
    )


@router.post("/query/stream")
async def query_stream_endpoint(req: QueryRequest, request: Request):
    """Streaming RAG pipeline via Server-Sent Events."""
    conn = request.app.state.pg_conn
    qdrant = request.app.state.qdrant
    redis_client = request.app.state.redis

    # Embed + retrieve + rerank (same as non-streaming)
    query_embedding = embed_batch([req.query])[0]

    if req.use_cache:
        cached = None
        try:
            cached = get_cached(query_embedding, redis_client)
        except Exception:
            pass
        if cached is not None:
            # Return cached response as a single SSE event
            async def _cached():
                yield f"data: {json.dumps({'token': cached.answer, 'done': True})}\n\n"
            return StreamingResponse(_cached(), media_type="text/event-stream")

    semantic_results = semantic_search(query_embedding, qdrant, req.filters)
    keyword_results = keyword_search(req.query, conn, req.filters)
    merged = reciprocal_rank_fusion(semantic_results, keyword_results)
    top_chunks = rerank(req.query, merged, req.top_k)

    if not top_chunks:
        async def _empty():
            yield f"data: {json.dumps({'token': 'No relevant information found.', 'done': True})}\n\n"
        return StreamingResponse(_empty(), media_type="text/event-stream")

    # Stream LLM tokens
    async def _stream():
        sources = [
            {"source_path": c.source_path, "section_path": c.section_path, "score": c.score}
            for c in top_chunks
        ]
        yield f"data: {json.dumps({'sources': sources})}\n\n"

        async for token in generate_stream(req.query, top_chunks):
            yield f"data: {json.dumps({'token': token})}\n\n"

        yield f"data: {json.dumps({'done': True})}\n\n"

    return StreamingResponse(_stream(), media_type="text/event-stream")
