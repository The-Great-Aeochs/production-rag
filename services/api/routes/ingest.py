"""Admin-only durable ingestion jobs, with no user-controlled absolute paths."""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from services.ingestion.jobs import enqueue
from shared.security import require_admin

router = APIRouter(tags=["ingest"], dependencies=[Depends(require_admin)])


class IngestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    corpus_id: str = Field(default="default", pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
    directory: str = Field(default=".", min_length=1, max_length=1024)


@router.post("/ingest", status_code=202)
def trigger_ingestion(req: IngestRequest, request: Request):
    try:
        with request.app.state.pg_pool.connection() as conn:
            job_id = enqueue(conn, req.directory, req.corpus_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"job_id": job_id, "status": "pending"}


@router.get("/ingest/{job_id}")
def get_job(job_id: str, request: Request):
    with request.app.state.pg_pool.connection() as conn:
        row = conn.execute(
            """SELECT status, total_docs, processed_docs, failed_docs, attempts, last_error,
               failed_paths FROM ingestion_jobs WHERE job_id=%s""",
            (job_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(404, "Job not found")
    return dict(
        zip(
            [
                "status",
                "total_docs",
                "processed_docs",
                "failed_docs",
                "attempts",
                "last_error",
                "failed_paths",
            ],
            row,
            strict=True,
        )
    )
