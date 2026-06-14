"""Query endpoints: full RAG pipeline, streaming, and session management."""

import json
import logging

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from shared.config import settings
from shared.models import ConversationMessage, QueryRequest, QueryResponse
from services.ingestion.embedder import embed_query
from services.query.generator import PROMPT_VERSION, generate_stream
from services.query.pipeline import (
    _count_tokens_approx,
    _safe_cache_get,
    _safe_cache_set,
    _safe_log_query,
    retrieve_and_rerank,
    run_query,
)
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
        pool=request.app.state.pg_pool,
        qdrant=request.app.state.qdrant,
        redis_client=request.app.state.redis,
    )


@router.post("/query/stream")
async def query_stream_endpoint(req: QueryRequest, request: Request):
    """Streaming RAG pipeline via Server-Sent Events."""
    pool = request.app.state.pg_pool
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
            token_count=_count_tokens_approx(req.query),
        ), redis_client)

    # Embed (possibly rewritten) query
    query_embedding = embed_query(search_query)

    # Cache check (keyed on rewritten query text)
    if req.use_cache:
        cached = _safe_cache_get(search_query, redis_client)
        if cached is not None:
            if session_id:
                add_message(session_id, ConversationMessage(
                    role="assistant",
                    content=cached.answer,
                    token_count=_count_tokens_approx(cached.answer),
                ), redis_client)
            async def _cached():
                yield f"data: {json.dumps({'token': cached.answer, 'done': True, 'session_id': session_id})}\n\n"
            return StreamingResponse(_cached(), media_type="text/event-stream")

    # Shared parallel retrieval + rerank
    top_chunks = retrieve_and_rerank(
        search_query, query_embedding, pool, qdrant, req.filters, req.top_k
    )

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

        answer_text = "".join(full_answer)

        # Save assistant response to session
        if session_id:
            add_message(session_id, ConversationMessage(
                role="assistant",
                content=answer_text,
                token_count=_count_tokens_approx(answer_text),
            ), redis_client)

        # Cache + log, parity with the blocking pipeline (best-effort)
        response = QueryResponse(
            answer=answer_text,
            sources=top_chunks,
            cached=False,
            session_id=session_id,
            model_used=settings.ollama_model,
            prompt_version=PROMPT_VERSION,
        )
        _safe_cache_set(search_query, response, redis_client)
        _safe_log_query(req, top_chunks, response, pool)

        yield f"data: {json.dumps({'done': True})}\n\n"

    return StreamingResponse(_stream(), media_type="text/event-stream")
