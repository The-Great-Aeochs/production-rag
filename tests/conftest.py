from contextlib import contextmanager
from unittest.mock import MagicMock

import fakeredis
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.api.middleware import RequestMiddleware
from services.api.routes import demo, health, ingest, query, workspaces
from shared.config import settings
from shared.models import RetrievalResult

TOKEN_A = "a" * 40
TOKEN_B = "b" * 40
ADMIN = "z" * 40


@pytest.fixture
def redis_client():
    return fakeredis.FakeRedis(decode_responses=True)


@pytest.fixture
def chunk():
    return RetrievalResult(
        chunk_id="chunk-1",
        content="The timeout is 30 seconds.",
        source_path="guide.md",
        section_path=["Config"],
        score=1,
        retrieval_method="hybrid",
    )


@pytest.fixture
def pool():
    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = (1,)

    class Pool:
        @contextmanager
        def connection(self):
            yield conn

    instance = Pool()
    instance.conn = conn
    return instance


@pytest.fixture
def client(monkeypatch, redis_client, pool):
    from pydantic import SecretStr

    monkeypatch.setattr(settings, "api_keys", {TOKEN_A: "alpha", TOKEN_B: "beta"})
    monkeypatch.setattr(settings, "admin_api_key", SecretStr(ADMIN))
    app = FastAPI()
    app.add_middleware(RequestMiddleware)
    app.include_router(query.router)
    app.include_router(ingest.router)
    app.include_router(health.router)
    app.include_router(workspaces.router)
    app.include_router(demo.router)
    app.state.redis = redis_client
    app.state.pg_pool = pool
    app.state.qdrant = MagicMock()
    app.state.models_ready = True
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


@pytest.fixture
def auth():
    return {"Authorization": f"Bearer {TOKEN_A}"}


@pytest.fixture
def jwt_signer(monkeypatch):
    import time
    from types import SimpleNamespace

    import jwt
    from cryptography.hazmat.primitives.asymmetric import rsa

    from shared import identity

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(settings, "jwt_issuer", "https://identity.example.test")
    monkeypatch.setattr(settings, "jwt_audience", "production-rag")
    monkeypatch.setattr(
        identity,
        "_jwks",
        lambda _: SimpleNamespace(
            get_signing_key_from_jwt=lambda _: SimpleNamespace(key=key.public_key())
        ),
    )

    def sign(subject="alice", **overrides):
        now = int(time.time())
        claims = {
            "sub": subject,
            "iat": now,
            "exp": now + 300,
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
        }
        claims.update(overrides)
        return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "test"})

    return sign
