"""Recoverable cross-store publication with Postgres as the authority.

A document is hidden from retrieval while pending/deleting. External writes are
idempotent and acknowledged before publication. A failed attempt stays visible
to the ingestion diff so a retry repairs it, even when its hash is unchanged.
"""

import io
import json
import mimetypes

import psycopg
from minio import Minio
from qdrant_client import QdrantClient
from qdrant_client.models import FieldCondition, Filter, FilterSelector, MatchValue, PointStruct

from shared.config import settings
from shared.models import Chunk


def bump_revision(conn, corpus_id: str) -> None:
    conn.execute(
        "INSERT INTO corpora(corpus_id, revision) VALUES (%s, 1) "
        "ON CONFLICT(corpus_id) DO UPDATE SET revision=corpora.revision+1",
        (corpus_id,),
    )


def _selector(doc_id: str) -> FilterSelector:
    return FilterSelector(
        filter=Filter(
            must=[
                FieldCondition(key="doc_id", match=MatchValue(value=doc_id)),
            ]
        )
    )


def write_document(
    doc_id: str,
    source_path: str,
    doc_type: str,
    language: str | None,
    raw_content: str,
    content_hash: str,
    metadata: dict,
    chunks: list[Chunk],
    conn: psycopg.Connection,
    qdrant: QdrantClient,
    minio_client: Minio,
    *,
    corpus_id: str = "default",
    raw_bytes: bytes | None = None,
    pipeline_version: str = "",
) -> None:
    if any(
        chunk.embedding is None or len(chunk.embedding) != settings.embedding_dim
        for chunk in chunks
    ):
        raise ValueError("Every chunk must have an embedding with the configured dimension")
    if any(chunk.doc_id != doc_id for chunk in chunks):
        raise ValueError("Chunk document IDs must match the parent")
    # Committed pending state is the durable repair record.
    with conn.transaction():
        bump_revision(conn, corpus_id)
        conn.execute(
            """INSERT INTO documents(doc_id, source_path, doc_type, language, raw_content,
                metadata, content_hash, embedding_model, corpus_id, sync_status, pipeline_version)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'pending',%s)
                ON CONFLICT(doc_id) DO UPDATE SET source_path=EXCLUDED.source_path,
                doc_type=EXCLUDED.doc_type, language=EXCLUDED.language,
                raw_content=EXCLUDED.raw_content, metadata=EXCLUDED.metadata,
                content_hash=EXCLUDED.content_hash, embedding_model=EXCLUDED.embedding_model,
                sync_status='pending', pipeline_version=EXCLUDED.pipeline_version, updated_at=NOW()""",
            (
                doc_id,
                source_path,
                doc_type,
                language,
                raw_content,
                json.dumps(metadata),
                content_hash,
                settings.embedding_model,
                corpus_id,
                pipeline_version,
            ),
        )
        conn.execute("DELETE FROM chunks WHERE doc_id=%s", (doc_id,))
        if chunks:
            with conn.cursor() as cur:
                cur.executemany(
                    """INSERT INTO chunks(chunk_id, doc_id, content, token_count, chunk_index,
                        parent_chunk_id, section_path, source_path, doc_type, language,
                        metadata, embedding_model, corpus_id)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    [
                        (
                            c.chunk_id,
                            c.doc_id,
                            c.content,
                            c.token_count,
                            c.chunk_index,
                            c.parent_chunk_id,
                            c.section_path,
                            c.source_path,
                            c.doc_type,
                            c.language,
                            json.dumps(c.metadata),
                            settings.embedding_model,
                            corpus_id,
                        )
                        for c in chunks
                    ],
                )
    qdrant.delete(
        collection_name=settings.qdrant_collection, points_selector=_selector(doc_id), wait=True
    )
    for i in range(0, len(chunks), 100):
        qdrant.upsert(
            collection_name=settings.qdrant_collection,
            wait=True,
            points=[
                PointStruct(
                    id=c.chunk_id,
                    vector=c.embedding,
                    payload={
                        "doc_id": doc_id,
                        "corpus_id": corpus_id,
                        "doc_type": doc_type,
                        "language": language or "",
                        "source_path": source_path,
                    },
                )
                for c in chunks[i : i + 100]
            ],
        )
    data = raw_bytes if raw_bytes is not None else raw_content.encode("utf-8")
    minio_client.put_object(
        settings.minio_bucket,
        f"{corpus_id}/{source_path}",
        io.BytesIO(data),
        len(data),
        content_type=mimetypes.guess_type(source_path)[0] or "application/octet-stream",
    )
    with conn.transaction():
        conn.execute("UPDATE documents SET sync_status='ready' WHERE doc_id=%s", (doc_id,))
        bump_revision(conn, corpus_id)


def delete_document(
    doc_id: str,
    source_path: str,
    conn: psycopg.Connection,
    qdrant: QdrantClient,
    minio_client: Minio,
    *,
    corpus_id: str = "default",
) -> None:
    with conn.transaction():
        conn.execute("UPDATE documents SET sync_status='deleting' WHERE doc_id=%s", (doc_id,))
        bump_revision(conn, corpus_id)
    qdrant.delete(
        collection_name=settings.qdrant_collection, points_selector=_selector(doc_id), wait=True
    )
    minio_client.remove_object(settings.minio_bucket, f"{corpus_id}/{source_path}")
    with conn.transaction():
        conn.execute("DELETE FROM documents WHERE doc_id=%s", (doc_id,))
        bump_revision(conn, corpus_id)
