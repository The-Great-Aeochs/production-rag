from unittest.mock import Mock

import pytest
from pydantic import SecretStr

from services.api.routes import demo
from shared.config import settings
from shared.models import QueryResponse


@pytest.fixture
def demo_enabled(monkeypatch):
    monkeypatch.setattr(settings, "demo_enabled", True)
    monkeypatch.setattr(settings, "demo_proxy_secret", SecretStr("d" * 40))
    return {"X-Demo-Key": "d" * 40}


def test_demo_is_disabled_by_default_and_needs_gateway_secret(client, demo_enabled, monkeypatch):
    assert client.post("/demo/query", json={"query": "q"}).status_code == 403
    monkeypatch.setattr(settings, "demo_enabled", False)
    assert client.post("/demo/query", headers=demo_enabled, json={"query": "q"}).status_code == 503


def test_demo_cannot_select_private_data_or_sessions(client, demo_enabled, monkeypatch):
    run = Mock(return_value=QueryResponse(answer="public"))
    monkeypatch.setattr(demo, "run_query", run)
    assert (
        client.post(
            "/demo/query",
            headers=demo_enabled,
            json={"query": "q", "filters": {"corpus_id": "private"}},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/demo/query", headers=demo_enabled, json={"query": "q", "session_id": "x"}
        ).status_code
        == 422
    )
    assert client.post("/demo/query", headers=demo_enabled, json={"query": "q"}).status_code == 200
    request = run.call_args.args[0]
    assert (
        request.filters == {"corpus_id": "public-demo"}
        and request.session_id is None
        and request.top_k == 3
    )


def test_demo_global_budget_cannot_be_bypassed_by_forwarded_ips(client, demo_enabled, monkeypatch):
    monkeypatch.setattr(settings, "demo_queries_per_day", 1)
    run = Mock(return_value=QueryResponse(answer="public"))
    monkeypatch.setattr(demo, "run_query", run)
    assert (
        client.post(
            "/demo/query",
            headers={**demo_enabled, "X-Forwarded-For": "1.1.1.1"},
            json={"query": "q"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/demo/query",
            headers={**demo_enabled, "X-Forwarded-For": "2.2.2.2"},
            json={"query": "q"},
        ).status_code
        == 429
    )
    run.assert_called_once()


def test_demo_quota_failure_fails_closed(client, demo_enabled, monkeypatch):
    monkeypatch.setattr(client.app.state.redis, "eval", Mock(side_effect=ConnectionError))
    run = Mock()
    monkeypatch.setattr(demo, "run_query", run)
    assert client.post("/demo/query", headers=demo_enabled, json={"query": "q"}).status_code == 503
    run.assert_not_called()
