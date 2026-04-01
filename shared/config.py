from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Postgres
    pg_host: str = "localhost"
    pg_port: int = 5432
    pg_user: str = "raguser"
    pg_password: str = "ragpass123"
    pg_db: str = "ragdb"

    # Qdrant
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "tech_docs"

    # MinIO
    minio_endpoint: str = "localhost:9000"
    minio_root_user: str = "minioadmin"
    minio_root_password: str = "minioadmin123"
    minio_bucket: str = "raw-docs"

    # Redis
    redis_url: str = "redis://localhost:6379"

    # Embedding
    embedding_model: str = "BAAI/bge-base-en-v1.5"
    embedding_dim: int = 768
    embedding_batch_size: int = 256

    # Chunking
    chunk_min_tokens: int = 256
    chunk_max_tokens: int = 1024
    chunk_overlap_ratio: float = 0.1

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
