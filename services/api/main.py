"""FastAPI application for the RAG system.

Manages client lifecycles via lifespan and mounts all route modules.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from shared.db import get_pg_pool, get_qdrant, get_redis_client, init_qdrant
from services.api.routes import health, ingest, query
from services.ingestion import embedder
from services.query import reranker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

log = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    # Startup: create shared clients
    app.state.pg_pool = get_pg_pool()
    app.state.qdrant = get_qdrant()
    app.state.redis = get_redis_client()
    init_qdrant(app.state.qdrant)

    # Warm the heavy local models so the first real query doesn't pay the
    # multi-second model-load cost inline.
    try:
        embedder.warmup()
        reranker.warmup()
    except Exception as e:  # best-effort — don't block startup on model load
        log.warning(f"Model warmup failed: {e}")

    log.info("All clients initialized")
    yield
    # Shutdown
    app.state.pg_pool.close()


app = FastAPI(
    title="Production RAG",
    version="0.2.0",
    lifespan=_lifespan,
)

app.include_router(query.router)
app.include_router(health.router)
app.include_router(ingest.router)
