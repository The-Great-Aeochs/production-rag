import importlib
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

main = importlib.import_module("services.api.main")


def clients(monkeypatch, pool):
    pool.close = Mock()
    pool.wait = Mock()
    qdrant, redis = Mock(), Mock()
    monkeypatch.setattr(main, "get_pg_pool", lambda: pool)
    monkeypatch.setattr(main, "get_qdrant", lambda: qdrant)
    monkeypatch.setattr(main, "get_redis_client", lambda: redis)
    monkeypatch.setattr(main.embedder, "warmup", Mock())
    monkeypatch.setattr(main.reranker, "warmup", Mock())
    return qdrant, redis


def test_lifecycle_closes_clients_and_resets_readiness(monkeypatch, pool):
    qdrant, redis = clients(monkeypatch, pool)
    with TestClient(main.app) as client:
        assert main.app.state.models_ready
        assert client.get("/health/live").status_code == 200
    assert not main.app.state.models_ready
    pool.close.assert_called_once()
    qdrant.close.assert_called_once()
    redis.close.assert_called_once()


def test_missing_migrations_fail_startup_and_close_resources(monkeypatch, pool):
    qdrant, redis = clients(monkeypatch, pool)
    pool.conn.execute.return_value.fetchone.return_value = None
    with pytest.raises(RuntimeError, match="scripts.migrate"), TestClient(main.app):
        pass
    pool.close.assert_called_once()
    qdrant.close.assert_called_once()
    redis.close.assert_called_once()


def test_model_warmup_failure_is_not_silently_marked_ready(monkeypatch, pool):
    qdrant, redis = clients(monkeypatch, pool)
    monkeypatch.setattr(main.embedder, "warmup", Mock(side_effect=RuntimeError("missing weights")))
    with pytest.raises(RuntimeError, match="missing weights"), TestClient(main.app):
        pass
    assert not main.app.state.models_ready
    pool.close.assert_called_once()
    qdrant.close.assert_called_once()
    redis.close.assert_called_once()
