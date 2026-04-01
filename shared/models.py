from datetime import datetime

from pydantic import BaseModel, Field


class Section(BaseModel):
    """Output of a parser. Represents a structural unit of a document."""

    title: str
    content: str
    level: int = 0  # heading depth: 0=root, 1=h1, 2=h2, etc.
    language: str | None = None  # for code blocks/files


class RawDocument(BaseModel):
    """Input to the ingestion pipeline."""

    source_path: str
    content: str
    doc_type: str  # "markdown" | "code" | "pdf"
    language: str | None = None
    metadata: dict = Field(default_factory=dict)


class Chunk(BaseModel):
    """Output of the chunker, input to embedder + writer."""

    chunk_id: str
    doc_id: str
    content: str
    token_count: int
    chunk_index: int
    parent_chunk_id: str | None = None
    section_path: list[str] = Field(default_factory=list)
    source_path: str
    doc_type: str
    language: str | None = None
    metadata: dict = Field(default_factory=dict)
    embedding: list[float] | None = None


class IngestionJob(BaseModel):
    """Tracks a bulk ingestion run."""

    job_id: str
    status: str = "pending"
    total_docs: int = 0
    processed_docs: int = 0
    failed_docs: int = 0
    failed_paths: list[str] = Field(default_factory=list)
    started_at: datetime = Field(default_factory=datetime.now)
    completed_at: datetime | None = None
    error_log: list[str] = Field(default_factory=list)
