"""Authenticated RAG routes; blocking preparation runs in FastAPI's threadpool."""

import json
import logging
import threading
from collections.abc import Iterator
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from services.query.generator import generate_stream
from services.query.pipeline import (
    NO_RESULTS,
    complete_query,
    prepare_query,
    release_query,
    run_query,
)
from services.query.session import create_session
from shared.config import settings
from shared.models import QueryRequest, QueryResponse
from shared.security import Principal, require_principal

log = logging.getLogger(__name__)
router = APIRouter(tags=["query"])
_slots = threading.BoundedSemaphore(settings.max_concurrent_queries)


def query_slot() -> Iterator[None]:
    if not _slots.acquire(blocking=False):
        raise HTTPException(503, "Query capacity exceeded", headers={"Retry-After": "1"})
    try:
        yield
    finally:
        _slots.release()


def scoped_request(req: QueryRequest, principal: Principal) -> QueryRequest:
    filters = dict(req.filters or {})
    if "corpus_id" in filters and filters["corpus_id"] != principal.corpus_id:
        raise HTTPException(403, "Corpus access denied")
    filters["corpus_id"] = principal.corpus_id
    return req.model_copy(update={"filters": filters})


@router.post("/session", status_code=201)
def create_session_endpoint(
    request: Request, principal: Annotated[Principal, Depends(require_principal)]
):
    return {"session_id": create_session(request.app.state.redis, principal.owner)}


@router.post("/query", response_model=QueryResponse, dependencies=[Depends(query_slot)])
def query_endpoint(
    req: QueryRequest, request: Request, principal: Annotated[Principal, Depends(require_principal)]
):
    if req.stream:
        raise HTTPException(422, "Use /query/stream for streaming")
    try:
        return run_query(
            scoped_request(req, principal),
            request.app.state.pg_pool,
            request.app.state.qdrant,
            request.app.state.redis,
            principal.owner,
        )
    except httpx.HTTPError as exc:
        raise HTTPException(503, "Generation is temporarily unavailable") from exc


def _event(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


@router.post("/query/stream")
def query_stream_endpoint(
    req: QueryRequest, request: Request, principal: Annotated[Principal, Depends(require_principal)]
):
    # Hold admission through the whole stream, including disconnect cleanup.
    if not _slots.acquire(blocking=False):
        raise HTTPException(503, "Query capacity exceeded", headers={"Retry-After": "1"})
    pool, redis_client = request.app.state.pg_pool, request.app.state.redis
    try:
        state = prepare_query(
            scoped_request(req, principal),
            pool,
            request.app.state.qdrant,
            redis_client,
            principal.owner,
        )
    except BaseException:
        _slots.release()
        raise

    async def stream():
        try:
            if state.cached:
                yield _event(
                    {
                        "token": state.cached.answer,
                        "sources": [s.model_dump() for s in state.cached.sources],
                        "cached": True,
                        "done": True,
                    }
                )
                return
            yield _event(
                {"sources": [s.model_dump() for s in state.chunks], "session_id": req.session_id}
            )
            parts = []
            if state.chunks:
                async for token in generate_stream(
                    state.search_query, state.chunks, state.history, state.summary
                ):
                    parts.append(token)
                    yield _event({"token": token})
            else:
                parts.append(NO_RESULTS)
                yield _event({"token": NO_RESULTS})
            await run_in_threadpool(complete_query, state, "".join(parts), pool, redis_client)
            yield _event({"done": True})
        except Exception:
            log.warning("Streaming query failed")
            yield _event({"error": "Query failed; please retry", "done": True})

    class ManagedStream(StreamingResponse):
        async def __call__(self, scope, receive, send):
            try:
                await super().__call__(scope, receive, send)
            finally:
                _slots.release()
                await run_in_threadpool(release_query, state)

    return ManagedStream(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
