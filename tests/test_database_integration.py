"""Real Postgres + Qdrant-local integration; object-store faults are injected.

Use TEST_DATABASE_URL for a disposable database. Every test gets an isolated
schema and never reads/writes application tables outside that schema.
"""

import hashlib
import os
import uuid
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock

import psycopg
import pytest
from psycopg import sql
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct

from services.ingestion import bulk_runner, jobs
from services.ingestion.writer import delete_document, write_document
from services.query.retriever import keyword_search, semantic_search
from shared.config import settings
from shared.db import init_qdrant
from shared.models import Chunk

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def db():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to run Postgres integration tests")
    schema = "test_" + uuid.uuid4().hex
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        conn.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
        conn.execute((ROOT / "services/ingestion/init.sql").read_text())
        for migration in sorted((ROOT / "migrations").glob("*.sql")):
            conn.execute(migration.read_text())
        try:
            yield conn
        finally:
            conn.rollback()
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


class ObjectStore:
    def __init__(self):
        self.objects = {}
        self.fail = False

    def bucket_exists(self, name):
        return True

    def put_object(self, bucket, key, stream, size, **kwargs):
        if self.fail:
            raise ConnectionError("object store unavailable")
        self.objects[key] = stream.read()

    def remove_object(self, bucket, key):
        if self.fail:
            raise ConnectionError("object store unavailable")
        self.objects.pop(key, None)


@pytest.fixture
def stores(monkeypatch):
    monkeypatch.setattr(settings, "embedding_dim", 2)
    monkeypatch.setattr(settings, "qdrant_collection", "test_" + uuid.uuid4().hex)
    client = (
        QdrantClient(url=os.environ["TEST_QDRANT_URL"])
        if os.environ.get("TEST_QDRANT_URL")
        else QdrantClient(":memory:")
    )
    init_qdrant(client)
    yield client, ObjectStore()
    client.delete_collection(settings.qdrant_collection)
    client.close()


def document(
    db, stores, *, corpus="alpha", source="guide.md", content="timeout configuration", raw=None
):
    qdrant, objects = stores
    doc_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{corpus}:{source}"))
    chunk_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{corpus}:{source}:{content}"))
    chunk = Chunk(
        chunk_id=chunk_id,
        doc_id=doc_id,
        source_path=source,
        content=content,
        doc_type="markdown",
        token_count=10,
        chunk_index=0,
        embedding=[1.0, 0.0],
    )
    write_document(
        doc_id,
        source,
        "markdown",
        None,
        content,
        hashlib.sha256(content.encode()).hexdigest(),
        {},
        [chunk],
        db,
        qdrant,
        objects,
        corpus_id=corpus,
        raw_bytes=raw,
        pipeline_version=bulk_runner.pipeline_version(),
    )
    return doc_id, chunk_id


def test_migrations_are_transactional_and_repeatable(db, monkeypatch):
    from scripts import migrate

    @contextmanager
    def borrowed(**kwargs):
        yield db

    monkeypatch.setattr(migrate, "get_pg_conn", borrowed)
    migrate.migrate()
    migrate.migrate()
    assert db.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 3


def test_both_retrieval_backends_enforce_corpus_and_source_filters(db, stores):
    document(db, stores, corpus="alpha", source="public.md")
    document(db, stores, corpus="alpha", source="private.md")
    document(db, stores, corpus="beta", source="public.md", content="timeout secret")
    filters = {"corpus_id": "alpha", "source_path": "public.md"}
    semantic = semantic_search([1.0, 0.0], stores[0], filters, conn=db)
    keyword = keyword_search("timeout", db, filters)
    assert [r.source_path for r in semantic] == ["public.md"]
    assert [r.source_path for r in keyword] == ["public.md"]
    assert "secret" not in str(semantic)


def test_original_pdf_bytes_are_preserved(db, stores):
    raw = b"%PDF-1.7\x00\xffbinary data"
    document(db, stores, source="guide.pdf", raw=raw)
    assert stores[1].objects["alpha/guide.pdf"] == raw


def test_failed_publication_stays_hidden_and_same_hash_is_repaired(db, stores):
    stores[1].fail = True
    with pytest.raises(ConnectionError):
        document(db, stores)
    assert db.execute("SELECT sync_status FROM documents").fetchone()[0] == "pending"
    assert keyword_search("timeout", db, {"corpus_id": "alpha"}) == []
    assert semantic_search([1.0, 0.0], stores[0], {"corpus_id": "alpha"}, conn=db) == []
    digest = hashlib.sha256(b"timeout configuration").hexdigest()
    assert bulk_runner.diff_against_db({"guide.md": digest}, db, "alpha")[1] == ["guide.md"]
    stores[1].fail = False
    document(db, stores)
    assert db.execute("SELECT sync_status FROM documents").fetchone()[0] == "ready"
    assert keyword_search("timeout", db, {"corpus_id": "alpha"})
    assert bulk_runner.diff_against_db({"guide.md": digest}, db, "alpha") == ([], [], [])


def test_stale_and_poisoned_vector_payloads_never_supply_answer_content(db, stores):
    _, chunk_id = document(db, stores)
    stores[0].upsert(
        settings.qdrant_collection,
        [
            PointStruct(
                id=chunk_id,
                vector=[1.0, 0.0],
                payload={"corpus_id": "alpha", "content": "poisoned"},
            ),
            PointStruct(
                id=str(uuid.uuid4()),
                vector=[1.0, 0.0],
                payload={"corpus_id": "alpha", "content": "deleted secret"},
            ),
        ],
    )
    results = semantic_search([1.0, 0.0], stores[0], {"corpus_id": "alpha"}, conn=db)
    assert len(results) == 1
    assert results[0].content == "timeout configuration"


def test_failed_delete_keeps_tombstone_for_retry_and_hides_document(db, stores):
    doc_id, _ = document(db, stores)
    stores[1].fail = True
    with pytest.raises(ConnectionError):
        delete_document(doc_id, "guide.md", db, *stores, corpus_id="alpha")
    assert db.execute("SELECT sync_status FROM documents").fetchone()[0] == "deleting"
    assert keyword_search("timeout", db, {"corpus_id": "alpha"}) == []
    stores[1].fail = False
    delete_document(doc_id, "guide.md", db, *stores, corpus_id="alpha")
    assert db.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] == 0


def test_other_corpora_are_not_deleted_by_snapshot_diff(db, stores):
    document(db, stores, corpus="alpha")
    document(db, stores, corpus="beta")
    assert bulk_runner.diff_against_db({}, db, "alpha")[2] == ["guide.md"]
    assert db.execute("SELECT COUNT(*) FROM documents WHERE corpus_id='beta'").fetchone()[0] == 1


def test_failed_jobs_retry_and_exhaustion_is_terminal(db, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "ingest_root", tmp_path)
    monkeypatch.setattr(settings, "ingestion_max_attempts", 2)
    (tmp_path / "alpha").mkdir()
    job_id = jobs.enqueue(db, ".", "alpha")
    run = Mock(side_effect=RuntimeError("transient"))
    monkeypatch.setattr(bulk_runner, "run", run)
    assert jobs.process_next(db)
    assert db.execute(
        "SELECT status, attempts FROM ingestion_jobs WHERE job_id=%s", (job_id,)
    ).fetchone() == ("pending", 1)
    db.execute("UPDATE ingestion_jobs SET next_attempt_at=NOW()")
    assert jobs.process_next(db)
    assert db.execute(
        "SELECT status, attempts FROM ingestion_jobs WHERE job_id=%s", (job_id,)
    ).fetchone() == ("failed", 2)
    assert not jobs.process_next(db)


def test_processing_job_recovers_when_worker_connection_dies(db, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "ingest_root", tmp_path)
    (tmp_path / "alpha").mkdir()
    job_id = jobs.enqueue(db, ".", "alpha")
    db.execute("UPDATE ingestion_jobs SET status='processing', attempts=1")

    def complete(*args, **kwargs):
        db.execute("UPDATE ingestion_jobs SET status='completed' WHERE job_id=%s", (job_id,))

    monkeypatch.setattr(bulk_runner, "run", complete)
    assert jobs.process_next(db)
    assert db.execute("SELECT status, attempts FROM ingestion_jobs").fetchone() == ("completed", 2)


def test_corpus_lock_prevents_duplicate_workers(db, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "ingest_root", tmp_path)
    (tmp_path / "alpha").mkdir()
    jobs.enqueue(db, ".", "alpha")
    run = Mock()
    monkeypatch.setattr(bulk_runner, "run", run)
    with psycopg.connect(os.environ["TEST_DATABASE_URL"], autocommit=True) as other:
        other.execute("SELECT pg_advisory_lock(%s)", (jobs.lock_id("alpha"),))
        assert not jobs.process_next(db)
        run.assert_not_called()
    # Connection close releases the corpus lock automatically.
    assert jobs.process_next(db)
    run.assert_called_once()


def test_full_worker_repairs_partial_publish_and_skips_successful_documents(
    db, stores, monkeypatch, tmp_path
):
    monkeypatch.setattr(settings, "ingest_root", tmp_path)
    root = tmp_path / "alpha"
    root.mkdir()
    (root / "guide.md").write_text("# Timeouts\nThe timeout is thirty seconds.")

    class BorrowedQdrant:
        def __getattr__(self, name):
            return getattr(stores[0], name)

        def close(self):
            pass

    monkeypatch.setattr(bulk_runner, "get_qdrant", BorrowedQdrant)
    monkeypatch.setattr(bulk_runner, "get_minio", lambda: stores[1])
    embed = Mock(side_effect=lambda texts: [[1.0, 0.0] for _ in texts])
    monkeypatch.setattr(bulk_runner, "embed_batch", embed)
    stores[1].fail = True
    job = jobs.enqueue(db, ".", "alpha")
    assert jobs.process_next(db)
    assert (
        db.execute("SELECT status FROM ingestion_jobs WHERE job_id=%s", (job,)).fetchone()[0]
        == "pending"
    )
    assert db.execute("SELECT sync_status FROM documents").fetchone()[0] == "pending"
    stores[1].fail = False
    db.execute("UPDATE ingestion_jobs SET next_attempt_at=NOW()")
    assert jobs.process_next(db)
    assert (
        db.execute("SELECT status FROM ingestion_jobs WHERE job_id=%s", (job,)).fetchone()[0]
        == "completed"
    )
    assert keyword_search("timeout", db, {"corpus_id": "alpha"})
    assert stores[1].objects["alpha/guide.md"] == (root / "guide.md").read_bytes()
    embed.reset_mock()
    jobs.enqueue(db, ".", "alpha")
    jobs.process_next(db)
    embed.assert_not_called()
    # An empty mount/snapshot cannot erase published data.
    (root / "guide.md").unlink()
    jobs.enqueue(db, ".", "alpha")
    jobs.process_next(db)
    assert db.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 1


def test_worker_crash_on_final_attempt_becomes_terminal(db, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "ingest_root", tmp_path)
    (tmp_path / "alpha").mkdir()
    jobs.enqueue(db, ".", "alpha")
    db.execute(
        "UPDATE ingestion_jobs SET status='processing', attempts=%s",
        (settings.ingestion_max_attempts,),
    )
    jobs.process_next(db)
    assert db.execute("SELECT status FROM ingestion_jobs").fetchone()[0] == "failed"
