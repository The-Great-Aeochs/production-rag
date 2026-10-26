"""Separate process liveness from dependency/model readiness."""

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from shared.config import settings
from shared.schema import SCHEMA_VERSION
from shared.security import require_admin

router = APIRouter(tags=["health"])


@router.get("/health/live")
def liveness():
    return {"status": "alive"}


@router.get("/health")
@router.get("/health/ready")
def readiness(request: Request):
    checks = {}
    operations = {
        "postgres": lambda: _ping_postgres(request.app.state.pg_pool),
        "qdrant": lambda: request.app.state.qdrant.collection_exists(settings.qdrant_collection),
        "redis": request.app.state.redis.ping,
        "ollama": _ping_ollama,
        "models": lambda: request.app.state.models_ready,
    }
    for name, operation in operations.items():
        try:
            checks[name] = bool(operation())
        except Exception:
            checks[name] = False
    ready = all(checks.values())
    return JSONResponse(
        {"status": "ready" if ready else "unavailable", "checks": checks},
        status_code=200 if ready else 503,
    )


def _ping_postgres(pool):
    with pool.connection() as conn:
        return (
            conn.execute(
                "SELECT 1 FROM schema_migrations WHERE version=%s", (SCHEMA_VERSION,)
            ).fetchone()
            is not None
        )


def _ping_ollama():
    response = httpx.get(f"{settings.ollama_url}/api/tags", timeout=settings.dependency_timeout_s)
    response.raise_for_status()
    # A live inference service without the configured model is not ready.
    return any(
        model.get("name") == settings.ollama_model for model in response.json().get("models", [])
    )


@router.get("/metrics", dependencies=[Depends(require_admin)])
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
