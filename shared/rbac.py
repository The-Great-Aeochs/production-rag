"""Workspace roles and transactional membership updates."""

from fastapi import HTTPException

ROLE_PERMISSIONS = {
    "member": frozenset({"query", "documents:read"}),
    "editor": frozenset({"query", "documents:read", "documents:sync"}),
    "admin": frozenset(
        {"query", "documents:read", "documents:sync", "members:manage", "audit:read"}
    ),
}


def membership(conn, corpus_id: str, user_id: str, permission: str = "query"):
    row = conn.execute(
        "SELECT role, version FROM workspace_memberships WHERE corpus_id=%s AND user_id=%s AND revoked_at IS NULL",
        (corpus_id, user_id),
    ).fetchone()
    if row is None or permission not in ROLE_PERMISSIONS[row[0]]:
        raise HTTPException(403, "Workspace access denied")
    return row


def change_membership(conn, corpus_id, actor_id, target_id, role: str | None):
    # Lock workspace before checking authorization, including last-admin checks.
    with conn.transaction():
        conn.execute("SELECT corpus_id FROM corpora WHERE corpus_id=%s FOR UPDATE", (corpus_id,))
        membership(conn, corpus_id, actor_id, "members:manage")
        current = conn.execute(
            "SELECT role FROM workspace_memberships WHERE corpus_id=%s AND user_id=%s AND revoked_at IS NULL",
            (corpus_id, target_id),
        ).fetchone()
        if current and current[0] == "admin" and role != "admin":
            count = conn.execute(
                "SELECT COUNT(*) FROM workspace_memberships WHERE corpus_id=%s AND role='admin' AND revoked_at IS NULL",
                (corpus_id,),
            ).fetchone()[0]
            if count <= 1:
                raise HTTPException(409, "A workspace must retain at least one admin")
        if not conn.execute("SELECT 1 FROM app_users WHERE user_id=%s", (target_id,)).fetchone():
            raise HTTPException(404, "User must sign in and open their workspace page first")
        if role is None:
            if not current:
                raise HTTPException(404, "Member not found")
            conn.execute(
                "UPDATE workspace_memberships SET revoked_at=NOW(), version=version+1 WHERE corpus_id=%s AND user_id=%s",
                (corpus_id, target_id),
            )
        else:
            conn.execute(
                """INSERT INTO workspace_memberships(corpus_id,user_id,role) VALUES (%s,%s,%s)
                   ON CONFLICT(corpus_id,user_id) DO UPDATE SET role=EXCLUDED.role,
                   revoked_at=NULL, version=workspace_memberships.version+1""",
                (corpus_id, target_id, role),
            )
        conn.execute(
            "INSERT INTO authorization_audit(corpus_id,actor_id,target_id,action,role) VALUES (%s,%s,%s,%s,%s)",
            (
                corpus_id,
                actor_id,
                target_id,
                "member.revoked" if role is None else "member.assigned",
                role,
            ),
        )
