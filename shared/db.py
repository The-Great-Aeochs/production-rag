import psycopg
import redis
import urllib3
from minio import Minio
from psycopg.conninfo import make_conninfo
from psycopg_pool import ConnectionPool
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    HnswConfigDiff,
    OptimizersConfigDiff,
    PayloadSchemaType,
    ScalarQuantization,
    ScalarQuantizationConfig,
    ScalarType,
    VectorParams,
)

from shared.config import settings


def get_redis_client() -> redis.Redis:
    return redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=settings.dependency_timeout_s,
        socket_timeout=settings.dependency_timeout_s,
    )


def _pg_conninfo() -> str:
    return make_conninfo(
        host=settings.pg_host,
        port=settings.pg_port,
        user=settings.pg_user,
        password=settings.pg_password,
        dbname=settings.pg_db,
        sslmode=settings.pg_sslmode,
        sslrootcert=settings.pg_sslrootcert,
        connect_timeout=max(1, int(settings.dependency_timeout_s)),
    )


def get_pg_conn(autocommit: bool = False) -> psycopg.Connection:
    """Open a standalone connection (for scripts: bulk ingestion, eval).

    The API server uses get_pg_pool() instead. Set autocommit=True for
    read-mostly callers so a failed query can't leave the connection stuck
    in an aborted-transaction state.
    """
    return psycopg.connect(
        host=settings.pg_host,
        port=settings.pg_port,
        user=settings.pg_user,
        password=settings.pg_password,
        dbname=settings.pg_db,
        sslmode=settings.pg_sslmode,
        sslrootcert=settings.pg_sslrootcert,
        autocommit=autocommit,
        connect_timeout=max(1, int(settings.dependency_timeout_s)),
    )


def _configure_pooled_conn(conn: psycopg.Connection) -> None:
    # Read-mostly query path: autocommit avoids open transactions lingering
    # after SELECTs and prevents one failed query from poisoning the
    # connection for the next request that checks it out of the pool.
    conn.autocommit = True
    conn.execute(
        "SELECT set_config('statement_timeout', %s, false)",
        (str(int(settings.dependency_timeout_s * 1000)),),
    )


def get_pg_pool() -> ConnectionPool:
    """Create a connection pool for the API server.

    A single shared connection is not safe across FastAPI's request
    threadpool; each request checks out its own connection from the pool.
    """
    pool = ConnectionPool(
        conninfo=_pg_conninfo(),
        min_size=settings.pg_pool_min_size,
        max_size=settings.pg_pool_max_size,
        configure=_configure_pooled_conn,
        open=True,
        timeout=settings.pg_pool_timeout_s,
        max_waiting=settings.max_concurrent_queries * 2,
    )
    return pool


def get_qdrant() -> QdrantClient:
    return QdrantClient(
        url=settings.qdrant_url,
        timeout=settings.dependency_timeout_s,
        api_key=settings.qdrant_api_key.get_secret_value() if settings.qdrant_api_key else None,
    )


def get_minio() -> Minio:
    return Minio(
        settings.minio_endpoint,
        access_key=settings.minio_root_user,
        secret_key=settings.minio_root_password,
        secure=settings.minio_secure,
        region=settings.minio_region or None,
        http_client=urllib3.PoolManager(
            timeout=urllib3.Timeout(
                connect=settings.dependency_timeout_s, read=settings.dependency_timeout_s
            ),
            retries=False,
        ),
    )


def init_qdrant(client: QdrantClient) -> None:
    """Create the tech_docs collection if it doesn't exist."""
    collections = [c.name for c in client.get_collections().collections]
    if settings.qdrant_collection not in collections:
        _create_collection(client)
    info = client.get_collection(settings.qdrant_collection)
    vectors = info.config.params.vectors
    if vectors is None or isinstance(vectors, dict) or vectors.size != settings.embedding_dim:
        raise ValueError("Embedding dimension mismatch: reindex into a new Qdrant collection")
    for field in ["doc_type", "language", "source_path", "corpus_id", "doc_id"]:
        if field in info.payload_schema:
            continue
        client.create_payload_index(
            collection_name=settings.qdrant_collection,
            field_name=field,
            field_schema=PayloadSchemaType.KEYWORD,
            wait=True,
        )


def _create_collection(client: QdrantClient) -> None:
    client.create_collection(
        collection_name=settings.qdrant_collection,
        vectors_config=VectorParams(
            size=settings.embedding_dim,
            distance=Distance.COSINE,
            hnsw_config=HnswConfigDiff(
                m=16,
                ef_construct=128,
                full_scan_threshold=10000,
            ),
            quantization_config=ScalarQuantization(
                scalar=ScalarQuantizationConfig(
                    type=ScalarType.INT8,
                    quantile=0.99,
                    always_ram=True,
                )
            ),
        ),
        optimizers_config=OptimizersConfigDiff(indexing_threshold=20000),
    )


def init_minio(client: Minio) -> None:
    """Create the raw-docs bucket if it doesn't exist."""
    if not client.bucket_exists(settings.minio_bucket):
        client.make_bucket(settings.minio_bucket)
