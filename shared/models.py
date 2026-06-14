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


class ConversationMessage(BaseModel):
    """A single message in a conversation session."""

    role: str  # "user" | "assistant"
    content: str
    token_count: int = 0


class QueryRequest(BaseModel):
    """Input to the query pipeline."""

    query: str
    session_id: str | None = None  # None = single-turn (no history)
    filters: dict | None = None
    top_k: int = 5
    use_cache: bool = True
    stream: bool = False


class RetrievalResult(BaseModel):
    """A single retrieved chunk with its score."""

    chunk_id: str
    content: str
    source_path: str
    section_path: list[str] = Field(default_factory=list)
    score: float
    retrieval_method: str  # "semantic" | "keyword" | "hybrid"


class QueryResponse(BaseModel):
    """Output of the query pipeline."""

    answer: str
    sources: list[RetrievalResult] = Field(default_factory=list)
    cached: bool = False
    session_id: str | None = None
    latency_ms: dict = Field(default_factory=dict)
    model_used: str = ""
    prompt_version: str = ""


class EvalCase(BaseModel):
    """A single test case for RAG evaluation."""

    id: str
    question: str
    expected_answer: str
    expected_sources: list[str] = Field(default_factory=list)  # file paths
    tags: list[str] = Field(default_factory=list)
    category: str = "factual"  # factual | code_search | conceptual | multi_hop | negative | ambiguous
    difficulty: str = "medium"  # easy | medium | hard
    expected_behavior: str = "answer"  # answer | refuse | clarify
    filters: dict | None = None


class EvalResult(BaseModel):
    """Result of evaluating a single test case."""

    case_id: str
    # Retrieval metrics
    hit: bool = False
    reciprocal_rank: float = 0.0
    precision_at_k: float = 0.0
    retrieved_sources: list[str] = Field(default_factory=list)
    # Generation metrics
    answer: str = ""
    faithfulness: float | None = None
    relevancy: int | None = None  # 1-3 scale
    correctness: int | None = None  # 1-3 scale
    citation_accuracy: float | None = None
    # Latency
    latency_ms: float = 0.0
    latency_breakdown: dict = Field(default_factory=dict)


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
