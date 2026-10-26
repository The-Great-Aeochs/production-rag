"""API lifecycle; schema changes are applied explicitly before deployment."""

import logging
from contextlib import ExitStack, asynccontextmanager

import psycopg
import redis
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from psycopg_pool import PoolTimeout, TooManyRequests

from services.api.middleware import RequestMiddleware
from services.api.routes import demo, health, ingest, query, workspaces
from services.ingestion import embedder
from services.query import reranker
from shared.db import get_pg_pool, get_qdrant, get_redis_client
from shared.schema import SCHEMA_VERSION

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def _lifespan(app: FastAPI):
    app.state.models_ready = False
    with ExitStack() as cleanup:
        app.state.pg_pool = get_pg_pool()
        cleanup.callback(app.state.pg_pool.close)
        app.state.qdrant = get_qdrant()
        cleanup.callback(app.state.qdrant.close)
        app.state.redis = get_redis_client()
        cleanup.callback(app.state.redis.close)
        app.state.pg_pool.wait()
        # Fail early on schema drift; never mutate schema in an API replica.
        with app.state.pg_pool.connection() as conn:
            if not conn.execute(
                "SELECT 1 FROM schema_migrations WHERE version=%s", (SCHEMA_VERSION,)
            ).fetchone():
                raise RuntimeError("Run python -m scripts.migrate before starting the API")
        embedder.warmup()
        reranker.warmup()
        app.state.models_ready = True
        try:
            yield
        finally:
            app.state.models_ready = False


app = FastAPI(title="Production RAG", version="0.4.0", lifespan=_lifespan)
app.add_middleware(RequestMiddleware)
app.include_router(query.router)
app.include_router(health.router)
app.include_router(ingest.router)
app.include_router(workspaces.router)
app.include_router(demo.router)


@app.exception_handler(redis.RedisError)
@app.exception_handler(PoolTimeout)
@app.exception_handler(TooManyRequests)
@app.exception_handler(psycopg.OperationalError)
async def dependency_unavailable(request: Request, exc: Exception):
    return JSONResponse({"detail": "Dependency temporarily unavailable"}, status_code=503)
