"""Exact response caching scoped to authorization, parameters and index revision.

Case is preserved: identifiers in source code can be case-sensitive. Multi-turn
responses are deliberately not cached because generation also uses history.
"""

import hashlib
import json

import redis

from shared.config import settings
from shared.models import QueryRequest, QueryResponse


def query_key(request: QueryRequest, owner: str, revision: int, prompt_version: str) -> str:
    scope = {
        "query": request.query,
        "filters": request.filters or {},
        "top_k": request.top_k,
        "owner": owner,
        "revision": revision,
        "collection": settings.qdrant_collection,
        "embedding": settings.embedding_model,
        "embedding_revision": settings.embedding_revision,
        "reranker": settings.reranker_model,
        "reranker_revision": settings.reranker_revision,
        "model": settings.ollama_model,
        "prompt": prompt_version,
        "max_tokens": settings.generation_max_tokens,
        "context_max_chars": settings.context_max_chars,
    }
    digest = hashlib.sha256(json.dumps(scope, sort_keys=True).encode()).hexdigest()
    return f"rag:cache:v2:{digest}"


def get_cached(key: str, client: redis.Redis) -> QueryResponse | None:
    data = client.get(key)
    return QueryResponse.model_validate_json(data) if data else None


def set_cached(key: str, response: QueryResponse, client: redis.Redis) -> None:
    # Store no session identifier or per-request timings.
    value = response.model_copy(update={"session_id": None, "latency_ms": {}})
    client.set(key, value.model_dump_json(), ex=settings.cache_ttl)
