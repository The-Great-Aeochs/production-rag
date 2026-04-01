"""Bulk ingestion orchestrator.

Scans a directory, diffs against Postgres to find new/changed/deleted
docs, then runs the parse → chunk → embed → write pipeline in batches.
Idempotent: re-running on the same corpus skips unchanged files.

Usage:
    python -m services.ingestion.bulk_runner --dir ./documents
"""

import argparse
import hashlib
import logging
import time
import uuid
from pathlib import Path

from services.ingestion.chunker import _make_id

from shared.config import settings
from shared.db import get_minio, get_pg_conn, get_qdrant, init_minio, init_qdrant
from services.ingestion.chunker import chunk_sections
from services.ingestion.embedder import embed_batch
from services.ingestion.parsers.registry import parse_file, supported_extensions
from services.ingestion.writer import delete_document, write_document

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger(__name__)

BATCH_SIZE = 100


def scan_directory(doc_dir: Path) -> dict[str, Path]:
    """Walk directory and collect files we can parse. Returns {relative_path: abs_path}."""
    extensions = supported_extensions()
    files: dict[str, Path] = {}

    for path in doc_dir.rglob("*"):
        if path.is_file() and path.suffix.lower() in extensions:
            rel = str(path.relative_to(doc_dir))
            files[rel] = path

    return files


def compute_hash(path: Path) -> str:
    """SHA-256 of file content."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def diff_against_db(
    files: dict[str, str], conn
) -> tuple[list[str], list[str], list[str]]:
    """Compare file hashes with Postgres. Returns (new, changed, deleted) paths."""
    # Get existing docs from Postgres
    rows = conn.execute(
        "SELECT source_path, content_hash FROM documents"
    ).fetchall()
    db_docs = {row[0]: row[1] for row in rows}

    new_paths = [p for p in files if p not in db_docs]
    changed_paths = [p for p in files if p in db_docs and files[p] != db_docs[p]]
    deleted_paths = [p for p in db_docs if p not in files]

    return new_paths, changed_paths, deleted_paths


def run(doc_dir: Path) -> None:
    """Run the full ingestion pipeline."""
    job_id = str(uuid.uuid4())[:8]
    start = time.time()
    log.info(f"Job {job_id}: scanning {doc_dir}")

    # Connect to all services
    conn = get_pg_conn()
    qdrant = get_qdrant()
    minio_client = get_minio()

    init_qdrant(qdrant)
    init_minio(minio_client)

    # 1. SCAN
    file_map = scan_directory(doc_dir)
    hash_map = {rel: compute_hash(abs_path) for rel, abs_path in file_map.items()}
    log.info(f"Job {job_id}: found {len(file_map)} files")

    new_paths, changed_paths, deleted_paths = diff_against_db(hash_map, conn)
    to_process = new_paths + changed_paths

    log.info(
        f"Job {job_id}: {len(new_paths)} new, {len(changed_paths)} changed, "
        f"{len(deleted_paths)} deleted, {len(file_map) - len(to_process)} unchanged"
    )

    # Record job start
    conn.execute(
        "INSERT INTO ingestion_jobs (job_id, status, total_docs) VALUES (%s, %s, %s)",
        (job_id, "processing", len(to_process) + len(deleted_paths)),
    )
    conn.commit()

    # 2. DELETE removed docs
    for rel_path in deleted_paths:
        doc_id = _make_id(rel_path)
        try:
            delete_document(doc_id, rel_path, conn, qdrant, minio_client)
        except Exception as e:
            log.error(f"Failed to delete {rel_path}: {e}")

    # 3. PARSE + CHUNK + EMBED + WRITE in batches
    processed = 0
    failed = 0
    failed_paths_list: list[str] = []
    error_log: list[str] = []

    for i in range(0, len(to_process), BATCH_SIZE):
        batch_paths = to_process[i : i + BATCH_SIZE]

        # Parse and chunk
        batch_chunks = []  # list of (rel_path, raw_content, doc_id, doc_type, language, metadata, chunks)
        for rel_path in batch_paths:
            abs_path = file_map[rel_path]
            try:
                sections, doc_type, language = parse_file(abs_path)
                chunks = chunk_sections(
                    sections,
                    source_path=rel_path,
                    doc_type=doc_type,
                    language=language,
                )
                raw_content = abs_path.read_text(encoding="utf-8", errors="replace")
                doc_id = _make_id(rel_path)

                batch_chunks.append(
                    (rel_path, raw_content, doc_id, doc_type, language, {}, chunks)
                )
            except Exception as e:
                failed += 1
                failed_paths_list.append(rel_path)
                error_log.append(f"{rel_path}: {e}")
                log.error(f"Parse/chunk failed for {rel_path}: {e}")

        if not batch_chunks:
            continue

        # Embed all chunks in this batch
        all_texts = []
        chunk_indices = []  # (batch_idx, chunk_idx) to map embeddings back
        for batch_idx, (_, _, _, _, _, _, chunks) in enumerate(batch_chunks):
            for chunk_idx, chunk in enumerate(chunks):
                all_texts.append(chunk.content)
                chunk_indices.append((batch_idx, chunk_idx))

        if all_texts:
            log.info(f"Embedding {len(all_texts)} chunks...")
            embeddings = embed_batch(all_texts)

            for (batch_idx, chunk_idx), embedding in zip(chunk_indices, embeddings):
                batch_chunks[batch_idx][6][chunk_idx].embedding = embedding

        # Write each document
        for rel_path, raw_content, doc_id, doc_type, language, metadata, chunks in batch_chunks:
            try:
                write_document(
                    doc_id=doc_id,
                    source_path=rel_path,
                    doc_type=doc_type,
                    language=language,
                    raw_content=raw_content,
                    content_hash=hash_map[rel_path],
                    metadata=metadata,
                    chunks=chunks,
                    conn=conn,
                    qdrant=qdrant,
                    minio_client=minio_client,
                )
                processed += 1
            except Exception as e:
                failed += 1
                failed_paths_list.append(rel_path)
                error_log.append(f"{rel_path}: {e}")
                log.error(f"Write failed for {rel_path}: {e}")

        log.info(f"Progress: {processed + failed}/{len(to_process)}")

    # 4. CLEANUP — update job record
    elapsed = time.time() - start
    conn.execute(
        """
        UPDATE ingestion_jobs SET
            status = %s,
            processed_docs = %s,
            failed_docs = %s,
            failed_paths = %s,
            error_log = %s,
            completed_at = NOW()
        WHERE job_id = %s
        """,
        (
            "completed" if failed == 0 else "completed_with_errors",
            processed + len(deleted_paths),
            failed,
            failed_paths_list,
            error_log,
            job_id,
        ),
    )
    conn.commit()
    conn.close()

    log.info(
        f"Job {job_id} done in {elapsed:.1f}s: "
        f"{len(new_paths)} new, {len(changed_paths)} updated, "
        f"{len(deleted_paths)} deleted, {failed} failed"
    )


def main():
    parser = argparse.ArgumentParser(description="Bulk document ingestion")
    parser.add_argument("--dir", required=True, help="Directory to ingest")
    args = parser.parse_args()

    doc_dir = Path(args.dir)
    if not doc_dir.is_dir():
        raise SystemExit(f"Not a directory: {doc_dir}")

    run(doc_dir)


if __name__ == "__main__":
    main()
