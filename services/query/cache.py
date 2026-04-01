"""Redis semantic cache for query responses.

Caches responses keyed by a hash of the query embedding (rounded to
2 decimal places). This means semantically similar queries hit the
same cache entry.
"""

import hashlib
import json
import logging

import redis

from shared.config import settings
from shared.models import QueryResponse

log = logging.getLogger(__name__)


def _embedding_key(embedding: list[float]) -> str:
    """Hash a rounded embedding to create a cache key."""
    rounded = [round(x, 2) for x in embedding]
    raw = json.dumps(rounded, separators=(",", ":"))
    return f"rag:cache:{hashlib.sha256(raw.encode()).hexdigest()[:16]}"


def get_cached(
    embedding: list[float], client: redis.Redis
) -> QueryResponse | None:
    """Look up a cached response by embedding similarity."""
    key = _embedding_key(embedding)
    data = client.get(key)
    if data is None:
        return None
    log.info(f"Cache hit: {key}")
    return QueryResponse.model_validate_json(data)


def set_cached(
    embedding: list[float],
    response: QueryResponse,
    client: redis.Redis,
    ttl: int | None = None,
) -> None:
    """Cache a response with TTL."""
    key = _embedding_key(embedding)
    client.setex(key, ttl or settings.cache_ttl, response.model_dump_json())
