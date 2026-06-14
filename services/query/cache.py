"""Redis cache for query responses.

Keyed by a normalized form of the (rewritten) query text. This is an exact
cache: the same question asked again hits, trivial variations (case,
whitespace) hit, anything else misses.

NOTE: this deliberately replaces the previous "round the embedding to 2
decimals and hash it" scheme. Rounding 768-dim normalized vectors (whose
components are ~±0.04) to 2 decimals collapsed most dimensions to 0.0, so
unrelated queries collided onto the same key and could be served each other's
answers. A true *semantic* cache (return a hit when a stored query is within a
cosine threshold) needs a similarity lookup over stored query embeddings — a
worthwhile Phase 3+ upgrade, but not something a hash can approximate safely.
"""

import hashlib
import logging
import re

import redis

from shared.config import settings
from shared.models import QueryResponse

log = logging.getLogger(__name__)


def _query_key(query: str) -> str:
    """Normalize and hash a query string into a cache key."""
    normalized = re.sub(r"\s+", " ", query.strip().lower())
    digest = hashlib.sha256(normalized.encode()).hexdigest()[:16]
    return f"rag:cache:{digest}"


def get_cached(query: str, client: redis.Redis) -> QueryResponse | None:
    """Look up a cached response by normalized query text."""
    key = _query_key(query)
    data = client.get(key)
    if data is None:
        return None
    log.info(f"Cache hit: {key}")
    return QueryResponse.model_validate_json(data)


def set_cached(
    query: str,
    response: QueryResponse,
    client: redis.Redis,
    ttl: int | None = None,
) -> None:
    """Cache a response with TTL, keyed by normalized query text."""
    key = _query_key(query)
    client.setex(key, ttl or settings.cache_ttl, response.model_dump_json())
