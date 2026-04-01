# CLAUDE.md — Production RAG System

## Project Overview

A production-grade Retrieval-Augmented Generation (RAG) system for technical documentation and codebases. Built from scratch (no LangChain/LlamaIndex) to maximise learning. Designed for lakhs of documents and queries. Free-tier infra where possible.

## Architecture

```
User/API Client
    ↓ HTTP/WebSocket
API Gateway (FastAPI)
    ↓
Query Pipeline | Ingestion Pipeline | Admin/Eval Service
    ↓
Data Layer: Qdrant (vectors) | Postgres+BM25 (metadata/keyword) | Redis (cache+queue) | MinIO (raw docs)
```

## Stack

| Layer | Technology | Notes |
|-------|-----------|-------|
| API | FastAPI | Async, typed, auto-docs |
| Vector DB | Qdrant (self-hosted) | 768-dim BGE vectors, filtered search |
| Keyword search | PostgreSQL + pg_trgm / ParadeDB | BM25 on same DB as metadata |
| Embeddings | BGE-base-en-v1.5 | Self-hosted via sentence-transformers, 768 dims |
| LLM | Ollama (Llama 3.1 8B) → Claude API | Start local, upgrade when needed |
| Task queue | Redis + Celery | Async ingestion, dead-letter queue for failures |
| Object store | MinIO | S3-compatible, raw doc storage |
| Container | Docker Compose → K8s (minikube) | Phase 1-3 Compose, Phase 4+ K8s |

## Project Structure

```
production-rag/
├── CLAUDE.md                           ← you are here
├── docker-compose.yml                  # Phase 1-3: local dev
├── .env.example                        # Template for environment variables
├── k8s/                                # Phase 4: K8s manifests
│   ├── deployments/
│   ├── services/
│   ├── configmaps/
│   └── secrets/
├── services/
│   ├── api/                            # FastAPI gateway
│   │   ├── Dockerfile
│   │   ├── main.py
│   │   ├── routes/                     # query.py, ingest.py, admin.py
│   │   └── middleware/                 # auth.py, rate_limit.py
│   ├── ingestion/                      # Ingestion pipeline
│   │   ├── Dockerfile
│   │   ├── parsers/                    # markdown_parser.py, code_parser.py, pdf_parser.py
│   │   ├── chunker.py                  # Structural + semantic chunking
│   │   ├── embedder.py                 # BGE via sentence-transformers
│   │   ├── writer.py                   # Qdrant + Postgres writer
│   │   └── bulk_runner.py              # Parallel bulk ingestion orchestrator
│   ├── query/                          # Query pipeline
│   │   ├── Dockerfile
│   │   ├── rewriter.py
│   │   ├── retriever.py                # Hybrid: Qdrant + Postgres BM25
│   │   ├── reranker.py                 # Cross-encoder: ms-marco-MiniLM-L-6-v2
│   │   ├── generator.py                # LLM with citations
│   │   └── cache.py                    # Redis semantic cache
│   └── eval/                           # Evaluation service
│       ├── eval_runner.py
│       ├── test_sets/v1.json
│       └── metrics.py
├── shared/
│   ├── models.py                       # Pydantic models (see Data Models section)
│   ├── config.py                       # pydantic-settings
│   └── db.py                           # DB connection helpers
├── scripts/
│   ├── seed_docs.py                    # Load sample docs for testing
│   └── run_eval.py                     # Run eval suite
├── prompts/
│   ├── system_v1.txt                   # Versioned system prompts
│   └── query_rewrite_v1.txt
└── documents/                          # Drop raw docs here for ingestion
```

---

## Data Models (shared/models.py)

These are the contracts between every service. Define them first, build around them.

```python
# --- Document & Chunk models (ingestion) ---

class RawDocument:
    """Input to the ingestion pipeline."""
    source_path: str              # e.g. "repos/myapp/src/auth.py"
    content: str                  # raw text content
    doc_type: str                 # "markdown" | "code" | "pdf"
    language: str | None          # "python", "typescript", etc. (for code)
    metadata: dict                # repo, branch, last_modified, author, etc.

class Chunk:
    """Output of the chunker, input to embedder + writer."""
    chunk_id: str                 # deterministic: hash(source_path + chunk_index)
    doc_id: str                   # hash(source_path)
    content: str                  # the actual chunk text
    token_count: int
    chunk_index: int              # position within the document
    parent_chunk_id: str | None   # for hierarchical context
    section_path: list[str]       # e.g. ["Authentication", "Middleware", "JWT Validation"]
    source_path: str
    doc_type: str
    language: str | None
    metadata: dict
    embedding: list[float] | None # filled by embedder, 768 dims

# --- Query models ---

class QueryRequest:
    query: str
    filters: dict | None          # e.g. {"repo": "myapp", "doc_type": "code", "language": "python"}
    top_k: int = 5
    use_cache: bool = True
    stream: bool = False

class RetrievalResult:
    chunk_id: str
    content: str
    source_path: str
    section_path: list[str]
    score: float                  # final score after reranking
    retrieval_method: str         # "semantic" | "keyword" | "hybrid"

class QueryResponse:
    answer: str
    sources: list[RetrievalResult]
    cached: bool
    latency_ms: dict              # {"retrieval": 120, "rerank": 45, "generation": 800, "total": 985}
    model_used: str
    prompt_version: str

# --- Ingestion tracking ---

class IngestionJob:
    job_id: str
    status: str                   # "pending" | "processing" | "completed" | "failed"
    total_docs: int
    processed_docs: int
    failed_docs: int
    failed_paths: list[str]       # which docs failed, for retry
    started_at: datetime
    completed_at: datetime | None
    error_log: list[str]

# --- Eval models ---

class EvalCase:
    question: str
    expected_answer: str
    expected_sources: list[str]   # file paths that should be retrieved
    tags: list[str]               # e.g. ["code-search", "conceptual", "multi-hop"]
```

---

## Database Schema (Postgres)

```sql
-- Core tables

CREATE TABLE documents (
    doc_id          TEXT PRIMARY KEY,           -- hash(source_path)
    source_path     TEXT UNIQUE NOT NULL,
    doc_type        TEXT NOT NULL,              -- markdown | code | pdf
    language        TEXT,
    raw_content     TEXT,                       -- optional: full text backup
    metadata        JSONB DEFAULT '{}',
    content_hash    TEXT NOT NULL,              -- hash of content, for change detection
    embedding_model TEXT NOT NULL,              -- "bge-base-en-v1.5" — track which model embedded this
    ingested_at     TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE chunks (
    chunk_id        TEXT PRIMARY KEY,           -- hash(source_path + chunk_index)
    doc_id          TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    content         TEXT NOT NULL,
    token_count     INT NOT NULL,
    chunk_index     INT NOT NULL,
    parent_chunk_id TEXT,
    section_path    TEXT[] DEFAULT '{}',        -- Postgres array for section hierarchy
    source_path     TEXT NOT NULL,
    doc_type        TEXT NOT NULL,
    language        TEXT,
    metadata        JSONB DEFAULT '{}',
    embedding_model TEXT NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT NOW(),

    -- For BM25 / full-text search
    search_vector   TSVECTOR GENERATED ALWAYS AS (
        setweight(to_tsvector('english', coalesce(source_path, '')), 'A') ||
        setweight(to_tsvector('english', coalesce(array_to_string(section_path, ' '), '')), 'B') ||
        setweight(to_tsvector('english', coalesce(content, '')), 'C')
    ) STORED
);

-- Indexes for performance at scale

CREATE INDEX idx_chunks_doc_id ON chunks(doc_id);
CREATE INDEX idx_chunks_source_path ON chunks(source_path);
CREATE INDEX idx_chunks_search_vector ON chunks USING GIN(search_vector);  -- BM25/FTS
CREATE INDEX idx_chunks_metadata ON chunks USING GIN(metadata);            -- filtered queries
CREATE INDEX idx_documents_content_hash ON documents(content_hash);        -- change detection

-- Query logging (observability)

CREATE TABLE query_logs (
    log_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    query_text      TEXT NOT NULL,
    filters         JSONB,
    retrieved_chunks JSONB,        -- [{chunk_id, score, method}]
    reranked_chunks JSONB,
    answer          TEXT,
    model_used      TEXT,
    prompt_version  TEXT,
    latency_ms      JSONB,         -- {retrieval, rerank, generation, total}
    cache_hit       BOOLEAN DEFAULT FALSE,
    user_feedback   TEXT,           -- "thumbs_up" | "thumbs_down" | null
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_query_logs_created ON query_logs(created_at DESC);

-- Ingestion jobs tracking

CREATE TABLE ingestion_jobs (
    job_id          TEXT PRIMARY KEY,
    status          TEXT NOT NULL DEFAULT 'pending',
    total_docs      INT DEFAULT 0,
    processed_docs  INT DEFAULT 0,
    failed_docs     INT DEFAULT 0,
    failed_paths    TEXT[] DEFAULT '{}',
    error_log       TEXT[] DEFAULT '{}',
    started_at      TIMESTAMPTZ DEFAULT NOW(),
    completed_at    TIMESTAMPTZ
);
```

---

## Qdrant Collection Configuration

```python
# Collection setup — do this once during initialization

COLLECTION_NAME = "tech_docs"

# HNSW parameters tuned for quality at moderate scale (up to ~10M vectors)
# For larger scale: increase m to 32, ef_construct to 256
qdrant_client.create_collection(
    collection_name=COLLECTION_NAME,
    vectors_config=VectorParams(
        size=768,                    # BGE-base-en-v1.5 output dimension
        distance=Distance.COSINE,    # cosine similarity for normalized embeddings
        hnsw_config=HnswConfigDiff(
            m=16,                    # connections per node (higher = better recall, more RAM)
            ef_construct=128,        # build-time search width (higher = better index, slower build)
            full_scan_threshold=10000,  # below this count, skip HNSW and brute-force
        ),
        quantization_config=ScalarQuantization(
            scalar=ScalarQuantizationConfig(
                type=ScalarType.INT8,     # 4x memory reduction with ~1% recall loss
                quantile=0.99,
                always_ram=True,          # keep quantized vectors in RAM for speed
            )
        ),
    ),
    # Payload indexes for filtered search (CRITICAL for performance)
    # Without these, filtered queries do full scan
    optimizers_config=OptimizersConfigDiff(
        indexing_threshold=20000,    # start indexing after this many vectors
    ),
)

# Create payload indexes for common filter fields
for field in ["doc_type", "language", "source_path"]:
    qdrant_client.create_payload_index(
        collection_name=COLLECTION_NAME,
        field_name=field,
        field_schema=PayloadSchemaType.KEYWORD,
    )

# When to shard:
# - Single node Qdrant handles ~5-10M vectors comfortably with INT8 quantization
# - Beyond that, enable sharding:
#   qdrant_client.create_collection(..., shard_number=3)
# - Each shard can live on a different node in cluster mode
```

**Collection strategy:**
- Start with ONE collection (`tech_docs`) for all documents
- Use payload filters for per-repo / per-type queries
- If you later need tenant isolation, create per-tenant collections
- Re-indexing plan: when changing embedding models, create `tech_docs_v2`, dual-write, switch, delete v1

---

## Bulk Ingestion Design

Ingesting lakhs of documents one-at-a-time through Celery is too slow. The bulk ingestion pipeline works differently:

```
bulk_runner.py orchestrates:

1. SCAN phase
   - Walk document directory / Git repo
   - Hash each file's content
   - Compare with documents.content_hash in Postgres
   - Build three lists: NEW docs, CHANGED docs, DELETED docs
   - Skip unchanged docs entirely (idempotent re-runs)

2. PARSE + CHUNK phase (parallel)
   - Process docs in batches of 100
   - Use multiprocessing.Pool or asyncio tasks
   - Each worker: parse → chunk → return list[Chunk]
   - Failed docs go to dead-letter list with error details

3. EMBED phase (batched)
   - Collect all chunks from step 2
   - Batch embed: 256 chunks per batch (optimal for GPU/CPU throughput)
   - sentence-transformers handles batching internally
   - On CPU: ~50-100 chunks/sec; on GPU: ~500-1000 chunks/sec

4. WRITE phase (batched + transactional)
   - Postgres: bulk INSERT with ON CONFLICT (chunk_id) DO UPDATE
   - Qdrant: upsert in batches of 100 points
   - Both writes for a doc succeed or both are rolled back
   - For DELETED docs: delete chunks from Postgres + Qdrant by doc_id

5. CLEANUP phase
   - Update ingestion_jobs table with final counts
   - Log failures for retry
   - Report: "Processed 1,23,456 docs. 234 new, 56 updated, 12 deleted, 3 failed."
```

**Idempotency:** The content_hash on each document means re-running ingestion on the same corpus is safe and fast — unchanged docs are skipped entirely.

**Progress tracking:**
```python
# During bulk ingestion, update progress in Redis for live monitoring
redis.hset(f"ingest:{job_id}", mapping={
    "status": "processing",
    "total": 50000,
    "processed": 12340,
    "failed": 3,
    "eta_seconds": 1820,
})
```

---

## Error Handling & Resilience

### Timeout Budgets (per query)

```
Total query budget:         4000ms (P95 target)
├── Query rewrite:           200ms  (skip if timeout pressure)
├── Retrieval (parallel):   1000ms
│   ├── Qdrant semantic:     500ms
│   └── Postgres BM25:       500ms
├── Reranking:               500ms  (degrade to no-rerank if slow)
├── LLM generation:         2000ms
└── Overhead (cache, I/O):   300ms
```

### Graceful Degradation

```python
# Pseudocode for resilient query pipeline

async def query_pipeline(request: QueryRequest) -> QueryResponse:
    # 1. Check cache first (fast path)
    cached = await cache.get_semantic(request.query)
    if cached:
        return cached  # ~5ms, skip everything

    # 2. Retrieval with timeout + fallback
    try:
        semantic_results = await asyncio.wait_for(
            qdrant_search(request), timeout=0.5
        )
    except asyncio.TimeoutError:
        semantic_results = []  # degrade: keyword-only
        log.warning("Qdrant timeout, falling back to keyword-only")

    try:
        keyword_results = await asyncio.wait_for(
            postgres_bm25_search(request), timeout=0.5
        )
    except asyncio.TimeoutError:
        keyword_results = []  # degrade: semantic-only
        log.warning("Postgres timeout, falling back to semantic-only")

    if not semantic_results and not keyword_results:
        return QueryResponse(answer="Search is temporarily unavailable. Please retry.", ...)

    # 3. Merge + rerank with fallback
    merged = reciprocal_rank_fusion(semantic_results, keyword_results)
    try:
        reranked = await asyncio.wait_for(rerank(merged), timeout=0.5)
    except asyncio.TimeoutError:
        reranked = merged[:5]  # degrade: skip reranking, use RRF order
        log.warning("Reranker timeout, using RRF ordering")

    # 4. Generate (no fallback — this is the core value)
    answer = await generate_with_citations(request.query, reranked)

    # 5. Cache + log (async, don't block response)
    asyncio.create_task(cache.set_semantic(request.query, answer))
    asyncio.create_task(log_query(request, reranked, answer))

    return answer
```

### Circuit Breaker Pattern

```python
# If Qdrant fails 5 times in 30 seconds, stop trying for 60 seconds
# Prevents cascade failures and gives the service time to recover

class CircuitBreaker:
    CLOSED = "closed"      # normal operation
    OPEN = "open"          # failing, skip calls
    HALF_OPEN = "half"     # testing if recovered

    def __init__(self, failure_threshold=5, recovery_timeout=60):
        self.state = self.CLOSED
        self.failure_count = 0
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.last_failure_time = None

# Apply to each downstream service:
qdrant_breaker = CircuitBreaker(failure_threshold=5, recovery_timeout=60)
postgres_breaker = CircuitBreaker(failure_threshold=5, recovery_timeout=60)
reranker_breaker = CircuitBreaker(failure_threshold=3, recovery_timeout=30)
```

### Health Checks

```python
# GET /health — verify ALL downstream dependencies
# Returns 200 only if critical services are reachable
# Used by K8s liveness/readiness probes and load balancers

async def health_check():
    checks = {
        "qdrant": await ping_qdrant(),       # critical
        "postgres": await ping_postgres(),   # critical
        "redis": await ping_redis(),         # degraded without it
        "ollama": await ping_ollama(),       # degraded without it (can use cache)
    }
    all_critical_ok = checks["qdrant"] and checks["postgres"]
    status = "healthy" if all_critical_ok else "unhealthy"
    return {"status": status, "checks": checks}
```

---

## Document Update & Deletion

Technical docs change constantly. The system handles this via content hashing:

```
On re-ingestion of a document:

1. Compute content_hash = sha256(file_content)
2. Look up existing doc by source_path in Postgres
3. Compare hashes:
   - SAME hash     → skip entirely (no work needed)
   - DIFFERENT hash → re-chunk, re-embed, upsert
   - NOT FOUND      → new document, full ingestion
4. For CHANGED docs:
   - Delete ALL old chunks (by doc_id) from Qdrant + Postgres
   - Re-chunk the new content
   - Re-embed and write new chunks
   - Update documents.content_hash and documents.updated_at
   - (We delete-then-insert rather than diffing chunks because
     chunk boundaries may shift when content changes)
5. For DELETED docs:
   - Delete from Qdrant by doc_id filter
   - CASCADE delete handles Postgres chunks
   - Delete raw file from MinIO
   - Remove documents row
```

**Why delete-and-reinsert, not diff?** When a paragraph is added in the middle of a document, every subsequent chunk's boundaries shift. Diffing chunks is fragile. Deleting all chunks for a doc and re-creating them is simpler, more reliable, and fast enough (a single doc re-ingestion takes < 2 seconds).

---

## Rate Limiting & Backpressure

```python
# API-level rate limiting (in middleware)

RATE_LIMITS = {
    "query": {
        "per_user": "60/minute",     # 1 query/sec sustained
        "global": "1000/minute",     # system-wide cap
        "burst": "10/second",        # short burst allowance
    },
    "ingest": {
        "per_user": "5/minute",      # ingestion is expensive
        "global": "20/minute",
    }
}

# When queue is full (backpressure):
# - Ingestion: return 429 with Retry-After header and job queue position
# - Queries: if Redis cache is available, serve cached results even if slightly stale
# - If system is overloaded, shed load by rejecting lowest-priority requests first

# Celery queue depth monitoring:
# - If queue depth > 1000 tasks: log warning, start rejecting new ingestion jobs
# - If queue depth > 5000 tasks: alert, scale up workers (K8s HPA in Phase 4)
```

---

## Build Phases

### Phase 1 — Ingestion Pipeline (current starting point)
- Docker Compose: Qdrant + Postgres + MinIO + Redis
- Document parsers: Markdown (headers/code blocks), code files (tree-sitter), PDF (pymupdf)
- Chunker: structural + semantic, 256-1024 tokens, parent-child relationships, 10-15% overlap
- Embedder: BGE-base-en-v1.5, batch mode, 768-dim output
- Writers: Qdrant (vectors+payload), Postgres (text+metadata), MinIO (raw files)
- Bulk runner with content hashing, parallel processing, progress tracking
- DB schema with indexes (GIN for tsvector, GIN for JSONB metadata)
- Qdrant collection with HNSW config, INT8 quantization, payload indexes
- **Milestone:** 1000 files indexed, verified via Qdrant UI nearest-neighbor query. Bulk re-run skips unchanged files.

### Phase 2 — Query Pipeline
- FastAPI endpoints: `POST /query`, `POST /query/stream`, `GET /health`, etc.
- Hybrid retrieval: Qdrant (top-30 semantic) + Postgres BM25 (top-30 keyword) → RRF merge
- Reranker: cross-encoder/ms-marco-MiniLM-L-6-v2, top-30 → top-5
- LLM generation with citation instructions, streaming
- Redis semantic cache (hash rounded embeddings, 1h/24h TTL)
- Timeout budgets per pipeline stage, graceful degradation
- Circuit breakers on Qdrant, Postgres, reranker
- Rate limiting middleware
- Per-query logging to query_logs table
- **Milestone:** Questions answered with citations. Graceful fallback when services are slow. Latency breakdown visible per query.

### Phase 3 — Quality + Eval
- 50-100 Q&A test pairs, RAGAS or custom eval harness
- Metrics: Hit Rate@5, MRR, Faithfulness, Answer Relevancy, P50/P95 latency
- Guardrails: groundedness check, low-confidence detection, input validation
- Observability: per-query logging (query, chunks, scores, latency), simple dashboard
- Prompt versioning: stored in `prompts/`, A/B testable
- Document update/delete pipeline tested (change a doc → verify chunks update)
- **Milestone:** Hit Rate > 85%, Faithfulness > 90%, P95 < 3s

### Phase 4 — Kubernetes
- Minikube → K3s → Oracle Cloud (4 ARM CPUs, 24GB RAM, always free)
- Stateless Deployments: api-gateway, query-worker, ingestion-worker
- StatefulSets: qdrant, postgres
- HPA on query workers (CPU/request count), PVCs, Ingress
- Liveness/readiness probes using /health endpoint
- **Milestone:** 10 concurrent users, HPA scales 1→3 workers under load

### Phase 5 — Advanced (when needed)
- Multi-tenancy (per-tenant Qdrant collections, Postgres RLS)
- Streaming ingestion (Git webhooks → auto re-ingest on push)
- Embedding model upgrades (dual-write to v1 + v2 collection, switch, delete v1)
- Model routing (cheap/fast vs expensive/quality based on query complexity)
- Document versioning (track which version of a doc a chunk came from)
- RBAC on retrieval (filter by user permissions before LLM sees chunks)
- Feedback loop (thumbs up/down stored in query_logs → fine-tune ranking)

---

## Key Implementation Rules

- **No LangChain/LlamaIndex.** Build from scratch. Use their ideas, not their abstractions.
- **Chunking:** Never fixed-size. Always structural (headers, function/class boundaries) + semantic. Maintain `parent_chunk_id`.
- **Retrieval:** Always hybrid (semantic + keyword). RRF for merging, cross-encoder for reranking.
- **LLM prompt:** Answer from context only. Cite as `[Source: filename#section]`. Say "I don't know" if context is insufficient.
- **Caching:** Hash rounded embeddings for semantic deduplication.
- **Idempotent ingestion:** Content hashing ensures re-runs are safe and skip unchanged docs.
- **Graceful degradation:** Every downstream call has a timeout. Every timeout has a fallback.
- **Evals run on every change** to chunking, embeddings, prompts, or retrieval logic.

## Quality Targets

| Metric | Target |
|--------|--------|
| Retrieval Hit Rate@5 | > 85% |
| Faithfulness | > 90% |
| P50 latency | < 2s |
| P95 latency | < 4s |
| Cache hit rate | > 30% |
| Embedding throughput | > 100 docs/min |
| Cost per query | < ₹0.5 |
| Ingestion idempotency | 100% (re-runs skip unchanged docs) |
| Graceful degradation | Partial results on any single service failure |

## Environment Setup

```bash
# Start all infra services
docker compose up -d

# Services will be available at:
# Qdrant UI:  http://localhost:6333/dashboard
# Postgres:   localhost:5432 (db: ragdb)
# MinIO UI:   http://localhost:9001
# Redis:      localhost:6379
```

Copy `.env.example` to `.env` and fill in secrets before running.

## Environment Variables

```
PG_PASSWORD=<postgres password>
MINIO_ROOT_USER=minioadmin
MINIO_ROOT_PASSWORD=<minio password>
REDIS_URL=redis://localhost:6379
QDRANT_URL=http://localhost:6333
OLLAMA_URL=http://localhost:11434
ANTHROPIC_API_KEY=<optional, for Claude API>
EMBEDDING_MODEL=BAAI/bge-base-en-v1.5
EMBEDDING_DIM=768
RERANKER_MODEL=cross-encoder/ms-marco-MiniLM-L-6-v2
CHUNK_MIN_TOKENS=256
CHUNK_MAX_TOKENS=1024
CHUNK_OVERLAP_RATIO=0.1
```

## Git Conventions

- Branch: `phase-1/ingestion`, `phase-2/query-pipeline`, etc.
- Commits: `feat:`, `fix:`, `eval:`, `infra:`, `docs:` prefixes
- Every phase milestone gets a tagged release: `v0.1.0-phase1`, `v0.2.0-phase2`, etc.
