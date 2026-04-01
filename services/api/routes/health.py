"""Health check endpoint for all downstream services."""

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from shared.config import settings

router = APIRouter(tags=["health"])


@router.get("/health")
def health_check(request: Request):
    checks = {
        "qdrant": _ping_qdrant(request.app.state.qdrant),
        "postgres": _ping_postgres(request.app.state.pg_conn),
        "redis": _ping_redis(request.app.state.redis),
        "ollama": _ping_ollama(),
    }
    all_critical = checks["qdrant"] and checks["postgres"]
    status = "healthy" if all_critical else "unhealthy"
    code = 200 if all_critical else 503
    return JSONResponse({"status": status, "checks": checks}, status_code=code)


def _ping_qdrant(client) -> bool:
    try:
        client.get_collections()
        return True
    except Exception:
        return False


def _ping_postgres(conn) -> bool:
    try:
        conn.execute("SELECT 1")
        return True
    except Exception:
        return False


def _ping_redis(client) -> bool:
    try:
        return client.ping()
    except Exception:
        return False


def _ping_ollama() -> bool:
    try:
        resp = httpx.get(f"{settings.ollama_url}/api/tags", timeout=2.0)
        return resp.status_code == 200
    except Exception:
        return False
