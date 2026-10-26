"""Bearer authentication with server-enforced corpus and session boundaries."""

import hashlib
import secrets
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from shared.config import settings
from shared.identity import Identity, verify_identity
from shared.rbac import membership

_bearer = HTTPBearer(auto_error=False)
_RATE_LIMIT = """
local n = redis.call('INCR', KEYS[1])
if n == 1 then redis.call('EXPIRE', KEYS[1], 60) end
return n
"""


@dataclass(frozen=True)
class Principal:
    owner: str
    corpus_id: str
    user_id: str | None = None
    role: str = "member"


def _token(credentials: HTTPAuthorizationCredentials | None) -> str:
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(401, "Bearer token required", headers={"WWW-Authenticate": "Bearer"})
    return credentials.credentials


def authenticate(token: str) -> Principal:
    if not settings.api_keys:
        raise HTTPException(503, "API authentication is not configured")
    for key, corpus in settings.api_keys.items():
        if secrets.compare_digest(token.encode(), key.encode()):
            return Principal(hashlib.sha256(f"{corpus}:{key}".encode()).hexdigest(), corpus)
    raise HTTPException(401, "Invalid bearer token", headers={"WWW-Authenticate": "Bearer"})


def rate_limit(request: Request, owner: str) -> None:
    try:
        count = request.app.state.redis.eval(_RATE_LIMIT, 1, f"rag:rate:{owner}")
    except Exception as exc:
        raise HTTPException(503, "Rate limit service unavailable") from exc
    if int(count) > settings.requests_per_minute:
        raise HTTPException(429, "Request limit exceeded", headers={"Retry-After": "60"})


def require_principal(
    request: Request, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]
) -> Principal:
    token = _token(credentials)
    if token in settings.api_keys:
        principal = authenticate(token)
    elif settings.jwt_issuer:
        identity = verify_identity(token)
        corpus = request.headers.get("X-Workspace-ID", "")
        import re

        if not re.fullmatch(r"ws_[a-f0-9]{32}", corpus):
            raise HTTPException(400, "Choose a workspace")
        with request.app.state.pg_pool.connection() as conn:
            role, version = membership(conn, corpus, identity.user_id)
        owner = hashlib.sha256(f"{identity.user_id}:{corpus}:{version}".encode()).hexdigest()
        principal = Principal(owner, corpus, identity.user_id, role)
    else:
        principal = authenticate(token)
    rate_limit(request, principal.user_id or principal.owner)
    return principal


def require_admin(
    request: Request, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]
) -> None:
    token = _token(credentials)
    key = settings.admin_api_key
    if key is None:
        raise HTTPException(503, "Admin API is not configured")
    if not secrets.compare_digest(token.encode(), key.get_secret_value().encode()):
        raise HTTPException(403, "Admin token required")
    rate_limit(request, "admin")


def require_identity(
    request: Request, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]
) -> Identity:
    identity = verify_identity(_token(credentials))
    rate_limit(request, identity.user_id)
    return identity
