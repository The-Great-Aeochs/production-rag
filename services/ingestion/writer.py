"""Write chunks to Qdrant, Postgres, and raw docs to MinIO.

Handles both single-document and batch writes. Uses upsert
semantics so re-ingestion is safe.
"""

import io
import logging

import psycopg
from minio import Minio
from qdrant_client import QdrantClient
from qdrant_client.models import FilterSelector, FieldCondition, Filter, MatchValue, PointStruct

from shared.config import settings
from shared.models import Chunk

log = logging.getLogger(__name__)

QDRANT_BATCH_SIZE = 100

_UPSERT_CHUNK_SQL = """
    INSERT INTO chunks (
        chunk_id, doc_id, content, token_count, chunk_index,
        parent_chunk_id, section_path, source_path, doc_type,
        language, metadata, embedding_model
    ) VALUES (
        %(chunk_id)s, %(doc_id)s, %(content)s, %(token_count)s, %(chunk_index)s,
        %(parent_chunk_id)s, %(section_path)s, %(source_path)s, %(doc_type)s,
        %(language)s, %(metadata)s, %(embedding_model)s
    )
    ON CONFLICT (chunk_id) DO UPDATE SET
        content = EXCLUDED.content,
        token_count = EXCLUDED.token_count,
        section_path = EXCLUDED.section_path,
        metadata = EXCLUDED.metadata
"""

_UPSERT_DOC_SQL = """
    INSERT INTO documents (
        doc_id, source_path, doc_type, language, raw_content,
        metadata, content_hash, embedding_model
    ) VALUES (
        %(doc_id)s, %(source_path)s, %(doc_type)s, %(language)s,
        %(raw_content)s, %(metadata)s, %(content_hash)s, %(embedding_model)s
    )
    ON CONFLICT (doc_id) DO UPDATE SET
        content_hash = EXCLUDED.content_hash,
        raw_content = EXCLUDED.raw_content,
        metadata = EXCLUDED.metadata,
        updated_at = NOW()
"""


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
) -> None:
    """Write a single document and its chunks to all stores."""
    import json

    embedding_model = settings.embedding_model

    # 1. Postgres: upsert document row, delete old chunks, insert new
    with conn.transaction():
        conn.execute(
            _UPSERT_DOC_SQL,
            {
                "doc_id": doc_id,
                "source_path": source_path,
                "doc_type": doc_type,
                "language": language,
                "raw_content": raw_content,
                "metadata": json.dumps(metadata),
                "content_hash": content_hash,
                "embedding_model": embedding_model,
            },
        )

        # Delete old chunks for this doc (new ones will be inserted)
        conn.execute("DELETE FROM chunks WHERE doc_id = %s", (doc_id,))

        for chunk in chunks:
            conn.execute(
                _UPSERT_CHUNK_SQL,
                {
                    "chunk_id": chunk.chunk_id,
                    "doc_id": chunk.doc_id,
                    "content": chunk.content,
                    "token_count": chunk.token_count,
                    "chunk_index": chunk.chunk_index,
                    "parent_chunk_id": chunk.parent_chunk_id,
                    "section_path": chunk.section_path,
                    "source_path": chunk.source_path,
                    "doc_type": chunk.doc_type,
                    "language": chunk.language,
                    "metadata": json.dumps(chunk.metadata),
                    "embedding_model": embedding_model,
                },
            )

    # 2. Qdrant: delete old points for this doc, upsert new
    qdrant.delete(
        collection_name=settings.qdrant_collection,
        points_selector=FilterSelector(
            filter=Filter(
                must=[FieldCondition(key="doc_id", match=MatchValue(value=doc_id))]
            )
        ),
    )

    points = [
        PointStruct(
            id=chunk.chunk_id,
            vector=chunk.embedding,
            payload={
                "doc_id": chunk.doc_id,
                "content": chunk.content,
                "source_path": chunk.source_path,
                "doc_type": chunk.doc_type,
                "language": chunk.language or "",
                "section_path": chunk.section_path,
                "chunk_index": chunk.chunk_index,
            },
        )
        for chunk in chunks
        if chunk.embedding is not None
    ]

    for i in range(0, len(points), QDRANT_BATCH_SIZE):
        batch = points[i : i + QDRANT_BATCH_SIZE]
        qdrant.upsert(collection_name=settings.qdrant_collection, points=batch)

    # 3. MinIO: store raw document
    data = raw_content.encode("utf-8")
    minio_client.put_object(
        settings.minio_bucket,
        source_path,
        io.BytesIO(data),
        len(data),
        content_type="text/plain",
    )

    log.info(f"Wrote {source_path}: {len(chunks)} chunks")


def delete_document(
    doc_id: str,
    source_path: str,
    conn: psycopg.Connection,
    qdrant: QdrantClient,
    minio_client: Minio,
) -> None:
    """Remove a document and all its chunks from all stores.

    Postgres delete is transactional (chunks cascade); the Qdrant and MinIO
    deletes are best-effort afterwards. If one of those fails, the bulk runner
    logs it and a subsequent re-run reconciles the orphan by doc_id.
    """
    with conn.transaction():
        conn.execute("DELETE FROM documents WHERE doc_id = %s", (doc_id,))

    qdrant.delete(
        collection_name=settings.qdrant_collection,
        points_selector=FilterSelector(
            filter=Filter(
                must=[FieldCondition(key="doc_id", match=MatchValue(value=doc_id))]
            )
        ),
    )

    try:
        minio_client.remove_object(settings.minio_bucket, source_path)
    except Exception:
        log.warning(f"Could not delete {source_path} from MinIO (may not exist)")

    log.info(f"Deleted {source_path}")
