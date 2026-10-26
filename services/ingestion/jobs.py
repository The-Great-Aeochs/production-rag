"""Postgres-backed durable queue; advisory locks recover automatically on crash.

Each worker holds a dedicated connection and corpus lock for the entire job.
A processing job whose worker died becomes eligible without lease races.
"""

import hashlib
import re
import uuid
from pathlib import Path

from shared.config import settings


class IngestionFailed(RuntimeError):
    pass


def lock_id(corpus_id: str) -> int:
    return int.from_bytes(
        hashlib.sha256(f"ingest:{corpus_id}".encode()).digest()[:8], "big", signed=True
    )


def resolve_directory(directory: str, corpus_id: str) -> Path:
    """Only ingest within ROOT/corpus_id, including resolved symlink targets."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", corpus_id):
        raise ValueError("Invalid corpus ID")
    root = (settings.ingest_root.resolve() / corpus_id).resolve()
    if not root.is_relative_to(settings.ingest_root.resolve()):
        raise ValueError("Corpus root escapes configured ingestion root")
    path = (root / directory).resolve()
    if not path.is_relative_to(root) or not path.is_dir():
        raise ValueError("Directory must exist inside its configured corpus root")
    if path != root:
        raise ValueError("Ingestion must snapshot the entire corpus root")
    return path


def enqueue(conn, directory: str, corpus_id: str) -> str:
    resolve_directory(directory, corpus_id)
    job_id = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO ingestion_jobs(job_id, corpus_id, directory, status) VALUES (%s,%s,%s,'pending')",
        (job_id, corpus_id, directory),
    )
    return job_id


def process_next(conn) -> bool:
    from services.ingestion.bulk_runner import run

    rows = conn.execute(
        """SELECT job_id, corpus_id, directory FROM ingestion_jobs
           WHERE status IN ('pending','processing') AND directory IS NOT NULL
           AND next_attempt_at <= NOW() ORDER BY created_at LIMIT 100""",
    ).fetchall()
    for job_id, corpus_id, directory in rows:
        key = lock_id(corpus_id)
        if not conn.execute("SELECT pg_try_advisory_lock(%s)", (key,)).fetchone()[0]:
            continue
        try:
            # Recheck after acquiring the lock: another worker may have finished.
            row = conn.execute(
                """UPDATE ingestion_jobs SET status='processing', attempts=attempts+1,
                   started_at=NOW(), completed_at=NULL
                   WHERE job_id=%s AND status IN ('pending','processing')
                   AND attempts < %s AND next_attempt_at <= NOW() RETURNING attempts""",
                (job_id, settings.ingestion_max_attempts),
            ).fetchone()
            if row is None:
                conn.execute(
                    """UPDATE ingestion_jobs SET status='failed', completed_at=NOW(),
                       last_error='Worker stopped during final attempt'
                       WHERE job_id=%s AND status='processing' AND attempts >= %s""",
                    (job_id, settings.ingestion_max_attempts),
                )
                continue
            try:
                path = resolve_directory(directory, corpus_id)
                run(path, corpus_id=corpus_id, conn=conn, job_id=job_id)
            except Exception as exc:
                # Autocommit connection + document transactions preserve repair state.
                conn.rollback()
                terminal = row[0] >= settings.ingestion_max_attempts
                conn.execute(
                    """UPDATE ingestion_jobs SET status=%s, last_error=%s,
                       next_attempt_at=NOW() + (%s * INTERVAL '1 second'),
                       completed_at=CASE WHEN %s THEN NOW() ELSE NULL END WHERE job_id=%s""",
                    (
                        "failed" if terminal else "pending",
                        type(exc).__name__,
                        min(300, 2 ** row[0]),
                        terminal,
                        job_id,
                    ),
                )
            return True
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", (key,))
    return False
