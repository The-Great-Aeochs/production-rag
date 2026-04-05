"""Query endpoints: full RAG pipeline, streaming, and session management."""

import json
import logging

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from shared.models import ConversationMessage, QueryRequest, QueryResponse
from services.ingestion.embedder import embed_batch
from services.query.cache import get_cached
from services.query.generator import generate_stream
from services.query.pipeline import run_query
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

router = APIRouter(tags=["query"])


@router.post("/session", status_code=201)
def create_session_endpoint(request: Request):
    """Create a new conversation session."""
    session_id = create_session(request.app.state.redis)
    return {"session_id": session_id}


@router.post("/query", response_model=QueryResponse)
def query_endpoint(req: QueryRequest, request: Request):
    """Full RAG pipeline: retrieve -> rerank -> generate.

    Pass session_id for multi-turn conversations. Omit for single-turn.
    """
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

    # Load session context if multi-turn
    history: list[ConversationMessage] = []
    summary: str | None = None
    session_id = req.session_id
    search_query = req.query

    if session_id:
        if not session_exists(session_id, redis_client):
            session_id = create_session(redis_client)

        history = get_recent_messages(session_id, redis_client)
        summary = get_summary(session_id, redis_client)

        # Rewrite query with context
        if history:
            search_query = rewrite_query(req.query, history, summary)

        # Save user message
        add_message(session_id, ConversationMessage(
            role="user",
            content=req.query,
            token_count=len(req.query) // 4,
        ), redis_client)

    # Embed + retrieve + rerank using (possibly rewritten) query
    query_embedding = embed_batch([search_query])[0]

    if req.use_cache:
        cached = None
        try:
            cached = get_cached(query_embedding, redis_client)
        except Exception:
            pass
        if cached is not None:
            if session_id:
                add_message(session_id, ConversationMessage(
                    role="assistant",
                    content=cached.answer,
                    token_count=len(cached.answer) // 4,
                ), redis_client)
            async def _cached():
                yield f"data: {json.dumps({'token': cached.answer, 'done': True, 'session_id': session_id})}\n\n"
            return StreamingResponse(_cached(), media_type="text/event-stream")

    semantic_results = semantic_search(query_embedding, qdrant, req.filters)
    keyword_results = keyword_search(search_query, conn, req.filters)
    merged = reciprocal_rank_fusion(semantic_results, keyword_results)
    top_chunks = rerank(search_query, merged, req.top_k)

    if not top_chunks:
        async def _empty():
            yield f"data: {json.dumps({'token': 'No relevant information found.', 'done': True, 'session_id': session_id})}\n\n"
        return StreamingResponse(_empty(), media_type="text/event-stream")

    # Stream LLM tokens
    async def _stream():
        sources = [
            {"source_path": c.source_path, "section_path": c.section_path, "score": c.score}
            for c in top_chunks
        ]
        yield f"data: {json.dumps({'sources': sources, 'session_id': session_id})}\n\n"

        full_answer = []
        async for token in generate_stream(search_query, top_chunks, history, summary):
            full_answer.append(token)
            yield f"data: {json.dumps({'token': token})}\n\n"

        # Save assistant response to session
        if session_id:
            answer_text = "".join(full_answer)
            add_message(session_id, ConversationMessage(
                role="assistant",
                content=answer_text,
                token_count=len(answer_text) // 4,
            ), redis_client)

        yield f"data: {json.dumps({'done': True})}\n\n"

    return StreamingResponse(_stream(), media_type="text/event-stream")
