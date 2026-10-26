"""Validated runtime configuration; production startup fails on unsafe defaults."""

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    environment: Literal["development", "test", "production"] = "development"
    # Bearer token -> corpus. Each token owns its own sessions and cache namespace.
    api_keys: dict[str, str] = Field(default_factory=dict, repr=False)
    admin_api_key: SecretStr | None = None
    jwt_issuer: str | None = None
    jwt_audience: str | None = None
    jwt_authorized_parties: list[str] = Field(default_factory=list)
    max_workspaces_per_user: int = Field(default=3, ge=1, le=100)
    demo_enabled: bool = False
    demo_proxy_secret: SecretStr | None = None
    demo_corpus_id: str = "public-demo"
    demo_queries_per_minute: int = Field(default=5, ge=1, le=60)
    demo_queries_per_day: int = Field(default=50, ge=1, le=10000)
    ingest_root: Path = Path("./documents")
    corpus_id: str = "default"
    requests_per_minute: int = Field(default=60, ge=1)
    max_concurrent_queries: int = Field(default=8, ge=1, le=128)
    max_request_bytes: int = Field(default=65536, ge=1024)
    log_query_content: bool = False

    pg_host: str = "localhost"
    pg_port: int = Field(default=5432, ge=1, le=65535)
    pg_user: str = "raguser"
    pg_password: str = Field(default="", repr=False)
    pg_db: str = "ragdb"
    pg_sslmode: str = "prefer"
    pg_sslrootcert: str | None = None
    pg_pool_min_size: int = Field(default=2, ge=1)
    pg_pool_max_size: int = Field(default=10, ge=1)
    pg_pool_timeout_s: float = Field(default=2.0, gt=0)
    dependency_timeout_s: float = Field(default=2.0, gt=0)

    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: SecretStr | None = None
    qdrant_collection: str = "tech_docs"
    minio_endpoint: str = "localhost:9000"
    minio_root_user: str = ""
    minio_root_password: str = Field(default="", repr=False)
    minio_bucket: str = "raw-docs"
    minio_secure: bool = False
    redis_url: str = Field(default="redis://localhost:6379", repr=False)
    cache_ttl: int = Field(default=3600, ge=1)
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "hf.co/unsloth/Qwen3-8B-GGUF:UD-Q4_K_XL"
    generation_timeout_s: float = Field(default=60.0, gt=0)
    rewrite_timeout_s: float = Field(default=3.0, gt=0)
    generation_max_tokens: int = Field(default=1024, ge=1, le=8192)
    context_max_chars: int = Field(default=16000, ge=1000, le=100000)
    anthropic_api_key: str | None = Field(default=None, repr=False)
    anthropic_model: str = "claude-opus-4-8"
    retrieval_timeout_s: float = Field(default=1.0, gt=0)
    session_ttl: int = Field(default=7200, ge=1)
    session_max_history: int = Field(default=10, ge=2, le=100)
    session_summary_token_threshold: int = Field(default=1500, ge=1)
    embedding_model: str = "BAAI/bge-base-en-v1.5"
    embedding_revision: str = "a5beb1e3e68b9ab74eb54cfd186867f64f240e1a"
    embedding_dim: int = Field(default=768, ge=1)
    embedding_batch_size: int = Field(default=256, ge=1)
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    reranker_revision: str = "233902d25c440f23af6f7d6e94d2946bac0bee0a"
    chunk_min_tokens: int = Field(default=256, ge=1)
    chunk_max_tokens: int = Field(default=1024, ge=1)
    chunk_overlap_ratio: float = Field(default=0.1, ge=0, lt=1)
    ingestion_max_attempts: int = Field(default=3, ge=1)
    ingestion_batch_size: int = Field(default=16, ge=1, le=100)
    max_document_bytes: int = Field(default=20_000_000, ge=1)

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @model_validator(mode="after")
    def validate_configuration(self):
        import re

        if self.pg_pool_min_size > self.pg_pool_max_size:
            raise ValueError("PG_POOL_MIN_SIZE must not exceed PG_POOL_MAX_SIZE")
        if self.chunk_min_tokens > self.chunk_max_tokens:
            raise ValueError("CHUNK_MIN_TOKENS must not exceed CHUNK_MAX_TOKENS")
        for corpus in [self.corpus_id, self.demo_corpus_id, *self.api_keys.values()]:
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", corpus):
                raise ValueError("Corpus IDs must be 1-64 letters, digits, underscores, or hyphens")
        tokens = list(self.api_keys)
        if self.admin_api_key:
            tokens.append(self.admin_api_key.get_secret_value())
        if any(len(token) < 32 for token in tokens):
            raise ValueError("API tokens must contain at least 32 characters")
        if self.admin_api_key and self.admin_api_key.get_secret_value() in self.api_keys:
            raise ValueError("Admin and query API tokens must differ")
        if bool(self.jwt_issuer) != bool(self.jwt_audience):
            raise ValueError("JWT_ISSUER and JWT_AUDIENCE must be configured together")
        if self.jwt_issuer:
            from urllib.parse import urlsplit

            parsed = urlsplit(self.jwt_issuer)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.query
                or parsed.fragment
                or parsed.username
            ):
                raise ValueError("JWT_ISSUER must be a trusted HTTPS issuer URL")
        if self.demo_proxy_secret and self.demo_proxy_secret.get_secret_value() in tokens:
            raise ValueError("DEMO_PROXY_SECRET must differ from privileged API keys")
        if self.demo_enabled and not self.demo_corpus_id.startswith("public-"):
            raise ValueError("The demo must use a dedicated public- corpus")
        if self.demo_enabled and (
            not self.demo_proxy_secret or len(self.demo_proxy_secret.get_secret_value()) < 32
        ):
            raise ValueError(
                "The public demo requires a separate DEMO_PROXY_SECRET of at least 32 characters"
            )
        if self.environment == "production":
            if not (self.api_keys or self.jwt_issuer) or not self.admin_api_key:
                raise ValueError(
                    "Production requires API_KEYS or JWT configuration, and ADMIN_API_KEY"
                )
            if not self.pg_password or not self.minio_root_user or not self.minio_root_password:
                raise ValueError(
                    "Production requires explicit database and object-store credentials"
                )
            if not self.minio_secure:
                raise ValueError("Production requires MINIO_SECURE=true")
            if not self.qdrant_api_key:
                raise ValueError("Production requires QDRANT_API_KEY")
        return self


settings = Settings()
