import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Barrier
from unittest.mock import Mock

import psycopg
import pytest
from fastapi import HTTPException
from psycopg import sql

from services.api.routes import query
from shared.config import settings
from shared.models import QueryResponse
from shared.rbac import change_membership
from tests import test_database_integration

db = test_database_integration.db

pytestmark = pytest.mark.integration


@pytest.fixture
def workspace_client(client, db):
    class Pool:
        @contextmanager
        def connection(self):
            yield db

    client.app.state.pg_pool = Pool()
    return client


def headers(jwt_signer, subject="alice", workspace=None, **claims):
    result = {"Authorization": f"Bearer {jwt_signer(subject, **claims)}"}
    if workspace:
        result["X-Workspace-ID"] = workspace
    return result


def create(client, jwt_signer, subject="alice"):
    response = client.post(
        "/workspaces", headers=headers(jwt_signer, subject), json={"name": "Engineering"}
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def register(client, jwt_signer, subject):
    return client.get("/workspaces", headers=headers(jwt_signer, subject)).json()["user_id"]


def test_workspace_is_server_generated_and_outsiders_cannot_query(workspace_client, jwt_signer):
    client = workspace_client
    workspace = create(client, jwt_signer)
    assert workspace.startswith("ws_") and len(workspace) == 35
    response = client.post(
        "/query",
        headers=headers(jwt_signer, "bob", workspace, role="admin"),
        json={"query": "secret"},
    )
    assert response.status_code == 403
    assert (
        client.get(
            f"/workspaces/{workspace}/documents", headers=headers(jwt_signer, "bob")
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/workspaces", headers=headers(jwt_signer), json={"name": "x", "corpus_id": "default"}
        ).status_code
        == 422
    )


def test_member_cannot_escalate_refresh_or_manage_other_members(workspace_client, jwt_signer):
    client = workspace_client
    workspace = create(client, jwt_signer)
    bob = register(client, jwt_signer, "bob")
    alice = register(client, jwt_signer, "alice")
    assert (
        client.put(
            f"/workspaces/{workspace}/members/{bob}",
            headers=headers(jwt_signer),
            json={"role": "member"},
        ).status_code
        == 200
    )
    forged = headers(jwt_signer, "bob", role="admin")
    assert (
        client.put(
            f"/workspaces/{workspace}/members/{alice}", headers=forged, json={"role": "member"}
        ).status_code
        == 403
    )
    assert client.post(f"/workspaces/{workspace}/ingest", headers=forged).status_code == 403
    assert client.get(f"/workspaces/{workspace}/audit", headers=forged).status_code == 403
    assert client.get(f"/workspaces/{workspace}/documents", headers=forged).status_code == 200


def test_role_change_revocation_and_readdition_do_not_resurrect_sessions(
    workspace_client, jwt_signer, db
):
    client = workspace_client
    workspace = create(client, jwt_signer)
    bob = register(client, jwt_signer, "bob")
    path = f"/workspaces/{workspace}/members/{bob}"
    client.put(path, headers=headers(jwt_signer), json={"role": "member"})
    bob_headers = headers(jwt_signer, "bob", workspace)
    session = client.post("/session", headers=bob_headers).json()["session_id"]
    assert client.put(path, headers=headers(jwt_signer), json={"role": "editor"}).status_code == 200
    assert (
        client.post(
            "/query", headers=bob_headers, json={"query": "q", "session_id": session}
        ).status_code
        == 404
    )
    assert client.delete(path, headers=headers(jwt_signer)).status_code == 204
    assert client.post("/query", headers=bob_headers, json={"query": "q"}).status_code == 403
    assert client.put(path, headers=headers(jwt_signer), json={"role": "member"}).status_code == 200
    assert (
        client.post(
            "/query", headers=bob_headers, json={"query": "q", "session_id": session}
        ).status_code
        == 404
    )
    assert (
        db.execute(
            "SELECT version FROM workspace_memberships WHERE user_id=%s AND corpus_id=%s",
            (bob, workspace),
        ).fetchone()[0]
        == 4
    )


def test_last_admin_is_protected_and_audit_is_written(workspace_client, jwt_signer):
    client = workspace_client
    workspace = create(client, jwt_signer)
    alice = register(client, jwt_signer, "alice")
    path = f"/workspaces/{workspace}/members/{alice}"
    assert client.put(path, headers=headers(jwt_signer), json={"role": "member"}).status_code == 409
    assert client.delete(path, headers=headers(jwt_signer)).status_code == 409
    events = client.get(f"/workspaces/{workspace}/audit", headers=headers(jwt_signer)).json()
    assert events[0]["action"] == "workspace.created"


def test_workspace_limit_cannot_be_bypassed_by_custom_ids(
    workspace_client, jwt_signer, monkeypatch
):
    monkeypatch.setattr(settings, "max_workspaces_per_user", 1)
    create(workspace_client, jwt_signer)
    response = workspace_client.post(
        "/workspaces", headers=headers(jwt_signer), json={"name": "Another"}
    )
    assert response.status_code == 409


def test_jwt_queries_use_membership_scope_not_browser_filters(
    workspace_client, jwt_signer, monkeypatch
):
    workspace = create(workspace_client, jwt_signer)
    run = Mock(return_value=QueryResponse(answer="yes"))
    monkeypatch.setattr(query, "run_query", run)
    response = workspace_client.post(
        "/query", headers=headers(jwt_signer, workspace=workspace), json={"query": "q"}
    )
    assert response.status_code == 200
    assert run.call_args.args[0].filters == {"corpus_id": workspace}
    assert (
        workspace_client.post(
            "/query",
            headers=headers(jwt_signer, workspace=workspace),
            json={"query": "q", "filters": {"corpus_id": "default"}},
        ).status_code
        == 403
    )


def test_concurrent_admin_demotions_keep_one_admin(workspace_client, jwt_signer, db):
    client = workspace_client
    workspace = create(client, jwt_signer)
    alice = register(client, jwt_signer, "alice")
    bob = register(client, jwt_signer, "bob")
    client.put(
        f"/workspaces/{workspace}/members/{bob}",
        headers=headers(jwt_signer),
        json={"role": "admin"},
    )
    schema = db.execute("SELECT current_schema()").fetchone()[0]
    barrier = Barrier(2)

    def demote(user_id):
        with psycopg.connect(os.environ["TEST_DATABASE_URL"], autocommit=True) as conn:
            conn.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
            barrier.wait(timeout=5)
            try:
                change_membership(conn, workspace, user_id, user_id, "member")
                return 200
            except HTTPException as exc:
                return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(demote, [alice, bob]))
    assert sorted(results) == [200, 409]
    assert (
        db.execute(
            "SELECT COUNT(*) FROM workspace_memberships WHERE corpus_id=%s AND role='admin' AND revoked_at IS NULL",
            (workspace,),
        ).fetchone()[0]
        == 1
    )


def test_workspace_admin_cannot_use_platform_admin_endpoints(workspace_client, jwt_signer):
    workspace = create(workspace_client, jwt_signer)
    auth = headers(jwt_signer, workspace=workspace)
    assert workspace_client.get("/metrics", headers=auth).status_code == 403
    assert (
        workspace_client.post("/ingest", headers=auth, json={"corpus_id": workspace}).status_code
        == 403
    )


def test_editor_refresh_uses_only_workspace_root_and_deduplicates_jobs(
    workspace_client, jwt_signer, monkeypatch, tmp_path, db
):
    monkeypatch.setattr(settings, "ingest_root", tmp_path)
    workspace = create(workspace_client, jwt_signer)
    bob = register(workspace_client, jwt_signer, "bob")
    workspace_client.put(
        f"/workspaces/{workspace}/members/{bob}",
        headers=headers(jwt_signer),
        json={"role": "editor"},
    )
    auth = headers(jwt_signer, "bob")
    path = f"/workspaces/{workspace}/ingest"
    assert workspace_client.post(path, headers=auth).status_code == 409
    (tmp_path / workspace).mkdir()
    response = workspace_client.post(path, headers=auth)
    assert response.status_code == 202
    again = workspace_client.post(path, headers=auth)
    assert again.json()["job_id"] == response.json()["job_id"]
    assert db.execute("SELECT corpus_id,directory FROM ingestion_jobs").fetchall() == [
        (workspace, ".")
    ]
    other = create(workspace_client, jwt_signer, "charlie")
    assert (
        workspace_client.get(
            f"/workspaces/{other}/jobs/{response.json()['job_id']}",
            headers=headers(jwt_signer, "charlie"),
        ).status_code
        == 404
    )
