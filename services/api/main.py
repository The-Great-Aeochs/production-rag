"""FastAPI application for the RAG system.

Manages client lifecycles via lifespan and mounts all route modules.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from shared.db import get_pg_conn, get_qdrant, get_redis_client, init_qdrant
from services.api.routes import health, ingest, query

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    # Startup: create shared clients
    app.state.pg_conn = get_pg_conn()
    app.state.qdrant = get_qdrant()
    app.state.redis = get_redis_client()
    init_qdrant(app.state.qdrant)
    logging.getLogger(__name__).info("All clients initialized")
    yield
    # Shutdown
    app.state.pg_conn.close()


app = FastAPI(
    title="Production RAG",
    version="0.2.0",
    lifespan=_lifespan,
)

app.include_router(query.router)
app.include_router(health.router)
app.include_router(ingest.router)
