"""User workspaces. Corpus IDs are server-generated and never self-assigned."""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from services.ingestion.jobs import enqueue
from shared.config import settings
from shared.identity import Identity, ensure_user
from shared.rbac import change_membership, membership
from shared.security import require_identity

router = APIRouter(prefix="/workspaces", tags=["workspaces"])
User = Annotated[Identity, Depends(require_identity)]


class WorkspaceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=80)


class MemberChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["member", "editor", "admin"]


@router.get("")
def list_workspaces(request: Request, user: User):
    with request.app.state.pg_pool.connection() as conn:
        ensure_user(conn, user)
        rows = conn.execute(
            """SELECT c.corpus_id, c.display_name, m.role FROM corpora c
               JOIN workspace_memberships m USING(corpus_id)
               WHERE m.user_id=%s AND m.revoked_at IS NULL ORDER BY c.created_at""",
            (user.user_id,),
        ).fetchall()
    return {
        "user_id": user.user_id,
        "workspaces": [{"id": r[0], "name": r[1], "role": r[2]} for r in rows],
    }


@router.post("", status_code=201)
def create_workspace(body: WorkspaceCreate, request: Request, user: User):
    corpus = "ws_" + uuid.uuid4().hex
    with request.app.state.pg_pool.connection() as conn, conn.transaction():
        ensure_user(conn, user)
        # Serialize creation per user so concurrent requests cannot bypass quota.
        conn.execute("SELECT user_id FROM app_users WHERE user_id=%s FOR UPDATE", (user.user_id,))
        count = conn.execute(
            "SELECT COUNT(*) FROM workspace_memberships WHERE user_id=%s AND role='admin' AND revoked_at IS NULL",
            (user.user_id,),
        ).fetchone()[0]
        if count >= settings.max_workspaces_per_user:
            raise HTTPException(409, "Workspace limit reached")
        conn.execute(
            "INSERT INTO corpora(corpus_id,display_name) VALUES (%s,%s)", (corpus, body.name)
        )
        conn.execute(
            "INSERT INTO workspace_memberships(corpus_id,user_id,role) VALUES (%s,%s,'admin')",
            (corpus, user.user_id),
        )
        conn.execute(
            "INSERT INTO authorization_audit(corpus_id,actor_id,action) VALUES (%s,%s,'workspace.created')",
            (corpus, user.user_id),
        )
    return {"id": corpus, "name": body.name, "role": "admin"}


@router.get("/{workspace_id}/members")
def list_members(workspace_id: str, request: Request, user: User):
    with request.app.state.pg_pool.connection() as conn:
        membership(conn, workspace_id, user.user_id, "members:manage")
        rows = conn.execute(
            "SELECT user_id,role FROM workspace_memberships WHERE corpus_id=%s AND revoked_at IS NULL ORDER BY user_id",
            (workspace_id,),
        ).fetchall()
    return [{"user_id": r[0], "role": r[1]} for r in rows]


@router.put("/{workspace_id}/members/{user_id}")
def put_member(workspace_id: str, user_id: str, body: MemberChange, request: Request, user: User):
    with request.app.state.pg_pool.connection() as conn:
        change_membership(conn, workspace_id, user.user_id, user_id, body.role)
    return {"user_id": user_id, "role": body.role}


@router.delete("/{workspace_id}/members/{user_id}", status_code=204)
def remove_member(workspace_id: str, user_id: str, request: Request, user: User):
    with request.app.state.pg_pool.connection() as conn:
        change_membership(conn, workspace_id, user.user_id, user_id, None)


@router.get("/{workspace_id}/documents")
def documents(workspace_id: str, request: Request, user: User):
    with request.app.state.pg_pool.connection() as conn:
        membership(conn, workspace_id, user.user_id, "documents:read")
        rows = conn.execute(
            "SELECT source_path,doc_type,sync_status,updated_at FROM documents WHERE corpus_id=%s ORDER BY source_path LIMIT 500",
            (workspace_id,),
        ).fetchall()
    return [{"source_path": r[0], "type": r[1], "status": r[2], "updated_at": r[3]} for r in rows]


@router.post("/{workspace_id}/ingest", status_code=202)
def sync_documents(workspace_id: str, request: Request, user: User):
    with request.app.state.pg_pool.connection() as conn, conn.transaction():
        conn.execute("SELECT corpus_id FROM corpora WHERE corpus_id=%s FOR UPDATE", (workspace_id,))
        membership(conn, workspace_id, user.user_id, "documents:sync")
        existing = conn.execute(
            "SELECT job_id,status FROM ingestion_jobs WHERE corpus_id=%s AND status IN ('pending','processing') ORDER BY created_at LIMIT 1",
            (workspace_id,),
        ).fetchone()
        if existing:
            return {"job_id": existing[0], "status": existing[1]}
        try:
            job = enqueue(conn, ".", workspace_id)
        except ValueError as exc:
            raise HTTPException(409, "No document source is connected to this workspace") from exc
        conn.execute(
            "INSERT INTO authorization_audit(corpus_id,actor_id,action) VALUES (%s,%s,'documents.synced')",
            (workspace_id, user.user_id),
        )
    return {"job_id": job, "status": "pending"}


@router.get("/{workspace_id}/jobs/{job_id}")
def job_status(workspace_id: str, job_id: str, request: Request, user: User):
    with request.app.state.pg_pool.connection() as conn:
        membership(conn, workspace_id, user.user_id, "documents:read")
        row = conn.execute(
            "SELECT status,total_docs,processed_docs,failed_docs FROM ingestion_jobs WHERE job_id=%s AND corpus_id=%s",
            (job_id, workspace_id),
        ).fetchone()
    if row is None:
        raise HTTPException(404, "Job not found")
    return dict(zip(["status", "total_docs", "processed_docs", "failed_docs"], row, strict=True))


@router.get("/{workspace_id}/audit")
def audit_events(workspace_id: str, request: Request, user: User):
    with request.app.state.pg_pool.connection() as conn:
        membership(conn, workspace_id, user.user_id, "audit:read")
        rows = conn.execute(
            "SELECT actor_id,target_id,action,role,created_at FROM authorization_audit WHERE corpus_id=%s ORDER BY created_at DESC LIMIT 100",
            (workspace_id,),
        ).fetchall()
    return [
        dict(zip(["actor_id", "target_id", "action", "role", "created_at"], r, strict=True))
        for r in rows
    ]
