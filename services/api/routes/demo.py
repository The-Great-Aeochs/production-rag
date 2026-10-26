"""Opt-in public demo: dedicated corpus, no sessions, and global hard quotas."""

import secrets
import time
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from services.api.routes.query import query_slot
from services.query.pipeline import run_query
from shared.config import settings
from shared.models import QueryRequest, QueryResponse

router = APIRouter(prefix="/demo", tags=["demo"])
_QUOTA = """
local minute = tonumber(redis.call('GET', KEYS[1]) or '0')
local day = tonumber(redis.call('GET', KEYS[2]) or '0')
if minute >= tonumber(ARGV[1]) then return 1 end
if day >= tonumber(ARGV[2]) then return 2 end
redis.call('INCR', KEYS[1]); redis.call('EXPIRE', KEYS[1], 61)
redis.call('INCR', KEYS[2]); redis.call('EXPIRE', KEYS[2], 86401)
return 0
"""


class DemoQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=1000)

    @field_validator("query")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Question cannot be blank")
        return value


@router.post("/query", response_model=QueryResponse, dependencies=[Depends(query_slot)])
def public_query(
    body: DemoQuery, request: Request, x_demo_key: Annotated[str | None, Header()] = None
):
    if not settings.demo_enabled:
        raise HTTPException(503, "Live demo is not enabled")
    key = settings.demo_proxy_secret
    if (
        key is None
        or not x_demo_key
        or not secrets.compare_digest(key.get_secret_value().encode(), x_demo_key.encode())
    ):
        raise HTTPException(403, "Demo gateway authorization required")
    now = int(time.time())
    try:
        exhausted = request.app.state.redis.eval(
            _QUOTA,
            2,
            f"rag:demo:minute:{now // 60}",
            f"rag:demo:day:{now // 86400}",
            settings.demo_queries_per_minute,
            settings.demo_queries_per_day,
        )
    except Exception as exc:
        raise HTTPException(503, "Demo quota service unavailable") from exc
    if exhausted:
        retry = 60 - now % 60 if exhausted == 1 else 86400 - now % 86400
        raise HTTPException(
            429, "Public demo quota reached. Please try later.", headers={"Retry-After": str(retry)}
        )
    req = QueryRequest(
        query=body.query, filters={"corpus_id": settings.demo_corpus_id}, top_k=3, use_cache=True
    )
    try:
        return run_query(
            req,
            request.app.state.pg_pool,
            request.app.state.qdrant,
            request.app.state.redis,
            owner="public-demo",
        )
    except httpx.HTTPError as exc:
        raise HTTPException(503, "Live answers temporarily unavailable") from exc
