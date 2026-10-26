"""Corpus-scoped, restartable ingestion with bounded document batches."""

import argparse
import hashlib
import json
import logging
from pathlib import Path

from services.ingestion.chunker import _make_id, chunk_sections
from services.ingestion.embedder import embed_batch
from services.ingestion.jobs import IngestionFailed, enqueue, process_next
from services.ingestion.parsers.registry import parse_file, supported_extensions
from services.ingestion.writer import delete_document, write_document
from shared.config import settings
from shared.db import get_minio, get_pg_conn, get_qdrant, init_minio, init_qdrant

log = logging.getLogger(__name__)


def pipeline_version() -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "version": 2,
                "embedding": settings.embedding_model,
                "embedding_revision": settings.embedding_revision,
                "min": settings.chunk_min_tokens,
                "max": settings.chunk_max_tokens,
                "overlap": settings.chunk_overlap_ratio,
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()


def scan_directory(doc_dir: Path) -> dict[str, Path]:
    root = doc_dir.resolve()
    files = {}
    for path in root.rglob("*"):
        if path.suffix.lower() not in supported_extensions():
            continue
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError("Symlinks outside the source tree are forbidden")
        if path.is_file():
            if path.stat().st_size > settings.max_document_bytes:
                raise ValueError("Document exceeds MAX_DOCUMENT_BYTES")
            files[path.relative_to(root).as_posix()] = path
    return files


def diff_against_db(files: dict[str, str], conn, corpus_id: str = "default"):
    rows = conn.execute(
        "SELECT source_path, content_hash, sync_status, pipeline_version FROM documents WHERE corpus_id=%s",
        (corpus_id,),
    ).fetchall()
    existing = {r[0]: r[1:] for r in rows}
    version = pipeline_version()
    return (
        [p for p in files if p not in existing],
        [p for p in files if p in existing and existing[p] != (files[p], "ready", version)],
        [p for p in existing if p not in files],
    )


def run(doc_dir: Path, *, corpus_id: str, conn, job_id: str) -> None:
    """Called while the worker holds the corpus advisory lock."""
    qdrant, minio = get_qdrant(), get_minio()
    try:
        init_qdrant(qdrant)
        init_minio(minio)
        # Every run owns an entire corpus root. Subdirectory snapshots would
        # otherwise interpret sibling documents as deletions.
        root = (settings.ingest_root.resolve() / corpus_id).resolve()
        if doc_dir.resolve() != root:
            raise ValueError("Ingestion must snapshot the entire corpus root")
        files = scan_directory(root)
        hashes = {p: hashlib.sha256(path.read_bytes()).hexdigest() for p, path in files.items()}
        new, changed, deleted = diff_against_db(hashes, conn, corpus_id)
        if not files and deleted:
            raise ValueError("Refusing to delete an entire corpus from an empty snapshot")
        failures = []
        processed = 0
        conn.execute(
            "UPDATE ingestion_jobs SET total_docs=%s, processed_docs=0, failed_docs=0 WHERE job_id=%s",
            (len(new) + len(changed) + len(deleted), job_id),
        )
        for source in deleted:
            try:
                row = conn.execute(
                    "SELECT doc_id FROM documents WHERE corpus_id=%s AND source_path=%s",
                    (corpus_id, source),
                ).fetchone()
                if row:
                    delete_document(row[0], source, conn, qdrant, minio, corpus_id=corpus_id)
                processed += 1
            except Exception:
                log.exception("Document deletion failed")
                failures.append(source)
        paths = new + changed
        version = pipeline_version()
        for offset in range(0, len(paths), settings.ingestion_batch_size):
            for source in paths[offset : offset + settings.ingestion_batch_size]:
                try:
                    path = files[source]
                    raw = path.read_bytes()
                    digest = hashlib.sha256(raw).hexdigest()
                    sections, doc_type, language = parse_file(path)
                    if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                        raise ValueError("Document changed during parsing; retry required")
                    chunks = chunk_sections(
                        sections,
                        source,
                        doc_type,
                        language,
                        identity=f"{corpus_id}:{source}:{digest}:{version}",
                    )
                    # Stable document ID; versioned chunk IDs reject old Qdrant points.
                    row = conn.execute(
                        "SELECT doc_id FROM documents WHERE corpus_id=%s AND source_path=%s",
                        (corpus_id, source),
                    ).fetchone()
                    doc_id = row[0] if row else _make_id(f"{corpus_id}:{source}")
                    embeddings = embed_batch([c.content for c in chunks]) if chunks else []
                    for chunk, vector in zip(chunks, embeddings, strict=True):
                        chunk.doc_id = doc_id
                        chunk.embedding = vector
                    write_document(
                        doc_id,
                        source,
                        doc_type,
                        language,
                        "\n\n".join(s.content for s in sections),
                        digest,
                        {},
                        chunks,
                        conn,
                        qdrant,
                        minio,
                        corpus_id=corpus_id,
                        raw_bytes=raw,
                        pipeline_version=version,
                    )
                    processed += 1
                except Exception:
                    log.exception("Document ingestion failed")
                    failures.append(source)
            conn.execute(
                "UPDATE ingestion_jobs SET processed_docs=%s, failed_docs=%s, failed_paths=%s WHERE job_id=%s",
                (processed, len(failures), failures, job_id),
            )
        conn.execute(
            "UPDATE ingestion_jobs SET processed_docs=%s, failed_docs=%s, failed_paths=%s WHERE job_id=%s",
            (processed, len(failures), failures, job_id),
        )
        if failures:
            raise IngestionFailed(f"{len(failures)} documents need retry")
        conn.execute(
            "UPDATE ingestion_jobs SET status='completed', last_error=NULL, completed_at=NOW() WHERE job_id=%s",
            (job_id,),
        )
    finally:
        qdrant.close()


def main():
    parser = argparse.ArgumentParser(description="Queue a corpus snapshot")
    parser.add_argument("--corpus", default=settings.corpus_id)
    parser.add_argument(
        "--run-once", action="store_true", help="Process one eligible queued job after enqueue"
    )
    args = parser.parse_args()
    with get_pg_conn(autocommit=True) as conn:
        print(enqueue(conn, ".", args.corpus))
        if args.run_once:
            process_next(conn)


if __name__ == "__main__":
    main()
