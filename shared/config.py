from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Postgres
    pg_host: str = "localhost"
    pg_port: int = 5432
    pg_user: str = "raguser"
    pg_password: str = "ragpass123"
    pg_db: str = "ragdb"
    pg_pool_min_size: int = 2
    pg_pool_max_size: int = 10

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
    cache_ttl: int = 3600  # 1 hour default

    # Ollama
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "hf.co/unsloth/Qwen3-8B-GGUF:UD-Q4_K_XL"

    # Anthropic (Claude API upgrade path — eval judge, optional generator backend)
    # The anthropic SDK also reads ANTHROPIC_API_KEY directly from the environment;
    # this field just makes the setting explicit/overridable.
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-opus-4-8"

    # Retrieval timeouts (graceful degradation — see pipeline.py)
    retrieval_timeout_s: float = 1.0  # per leg (semantic / keyword), runs in parallel

    # Session / multi-turn
    session_ttl: int = 7200  # 2 hours
    session_max_history: int = 10  # max verbatim messages (5 exchanges)
    session_summary_token_threshold: int = 1500  # summarize when history exceeds this

    # Embedding
    embedding_model: str = "BAAI/bge-base-en-v1.5"
    embedding_dim: int = 768
    embedding_batch_size: int = 256

    # Reranker
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    # Chunking
    chunk_min_tokens: int = 256
    chunk_max_tokens: int = 1024
    chunk_overlap_ratio: float = 0.1

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
