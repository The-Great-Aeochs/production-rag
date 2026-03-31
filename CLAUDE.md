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
| Task queue | Redis + Celery | Async ingestion |
| Object store | MinIO | S3-compatible, raw doc storage |
| Container | Docker Compose → K8s (minikube) | Phase 1-3 Compose, Phase 4+ K8s |

## Project Structure

```
production-rag/
├── CLAUDE.md                           ← you are here
├── docker-compose.yml                  # Phase 1-3: local dev
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
│   │   └── writer.py                   # Qdrant + Postgres writer
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
│   ├── models.py                       # Pydantic models
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

## Build Phases

### Phase 1 — Ingestion Pipeline (current starting point)
- Docker Compose: Qdrant + Postgres + MinIO + Redis
- Document parsers: Markdown (headers/code blocks), code files (tree-sitter), PDF (pymupdf)
- Chunker: structural + semantic, 256-1024 tokens, parent-child relationships, 10-15% overlap
- Embedder: BGE-base-en-v1.5, batch mode, 768-dim output
- Writers: Qdrant (vectors+payload), Postgres (text+metadata), MinIO (raw files)
- **Milestone:** 1000 files indexed, verified via Qdrant UI nearest-neighbor query

### Phase 2 — Query Pipeline
- FastAPI endpoints: `POST /query`, `POST /query/stream`, `GET /health`, etc.
- Hybrid retrieval: Qdrant (top-30 semantic) + Postgres BM25 (top-30 keyword) → RRF merge
- Reranker: cross-encoder/ms-marco-MiniLM-L-6-v2, top-30 → top-5
- LLM generation with citation instructions, streaming
- Redis semantic cache (hash rounded embeddings, 1h/24h TTL)
- **Milestone:** Questions answered with citations, latency/quality measured

### Phase 3 — Quality + Eval
- 50-100 Q&A test pairs, RAGAS or custom eval harness
- Metrics: Hit Rate@5, MRR, Faithfulness, Answer Relevancy, P50/P95 latency
- Guardrails: groundedness check, low-confidence detection, input validation
- Observability: per-query logging (query, chunks, scores, latency), simple dashboard
- Prompt versioning: stored in `prompts/`, A/B testable
- **Milestone:** Hit Rate > 85%, Faithfulness > 90%, P95 < 3s

### Phase 4 — Kubernetes
- Minikube → K3s → Oracle Cloud (4 ARM CPUs, 24GB RAM, always free)
- Stateless Deployments: api-gateway, query-worker, ingestion-worker
- StatefulSets: qdrant, postgres
- HPA on query workers (CPU/request count), PVCs, Ingress
- **Milestone:** 10 concurrent users, HPA scales 1→3 workers under load

### Phase 5 — Advanced (when needed)
- Multi-tenancy, streaming ingestion (Git webhooks), embedding model upgrades (dual-write)
- Model routing (cheap/fast vs expensive/quality), document versioning, RBAC on retrieval
- Feedback loop (thumbs up/down → ranking fine-tune)

## Key Implementation Rules

- **No LangChain/LlamaIndex.** Build from scratch. Use their ideas, not their abstractions.
- **Chunking:** Never fixed-size. Always structural (headers, function/class boundaries) + semantic. Maintain `parent_chunk_id`.
- **Retrieval:** Always hybrid (semantic + keyword). RRF for merging, cross-encoder for reranking.
- **LLM prompt:** Answer from context only. Cite as `[Source: filename#section]`. Say "I don't know" if context is insufficient.
- **Caching:** Hash rounded embeddings for semantic deduplication.
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
OLLAMA_URL=http://localhost:11434   # or Claude API key
ANTHROPIC_API_KEY=<optional, for Claude API>
```

## Git Conventions

- Branch: `phase-1/ingestion`, `phase-2/query-pipeline`, etc.
- Commits: `feat:`, `fix:`, `eval:`, `infra:`, `docs:` prefixes
- Every phase milestone gets a tagged release: `v0.1.0-phase1`, `v0.2.0-phase2`, etc.
