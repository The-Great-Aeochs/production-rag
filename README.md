# Production RAG

A production-grade Retrieval-Augmented Generation system for technical documentation and codebases. Built from scratch — no LangChain, no LlamaIndex.

## Architecture

```
User/API Client
    |
    v
FastAPI Gateway
    |
    v
Query Pipeline                    Ingestion Pipeline
  session load (Redis)              parse (Markdown/Code/PDF)
  query rewrite (multi-turn)        chunk (structural, 256-1024 tokens)
  hybrid retrieval                  embed (BGE-base-en-v1.5, 768-dim)
    Qdrant (semantic)               write (Qdrant + Postgres + MinIO)
    Postgres (BM25 keyword)
  cross-encoder rerank
  LLM generation (Ollama)
  Redis cache
    |
    v
Data Layer
  Qdrant (vectors) | Postgres+BM25 (metadata) | Redis (cache+sessions) | MinIO (raw docs)
```

## Stack

| Component | Technology |
|-----------|-----------|
| API | FastAPI |
| Vector DB | Qdrant (self-hosted, HNSW + INT8 quantization) |
| Keyword search | PostgreSQL (tsvector, weighted BM25) |
| Embeddings | BGE-base-en-v1.5 via sentence-transformers |
| Reranker | cross-encoder/ms-marco-MiniLM-L-6-v2 |
| LLM | Ollama (Qwen3-8B locally, Claude API upgrade path) |
| Cache + Sessions | Redis |
| Object store | MinIO |

## Features

- **Hybrid retrieval** — semantic (Qdrant) + keyword (Postgres BM25), merged via Reciprocal Rank Fusion
- **Cross-encoder reranking** — ms-marco-MiniLM-L-6-v2 rescores top results
- **Multi-turn conversations** — Redis session store, context-aware query rewriting for follow-up questions
- **Structural chunking** — respects headings, function/class boundaries (tree-sitter for code), parent-child relationships
- **Semantic caching** — hashed embeddings as cache keys, sub-100ms cache hits
- **Graceful degradation** — every downstream call has a timeout and fallback
- **Idempotent ingestion** — content hashing skips unchanged documents on re-runs
- **Citation support** — LLM answers cite sources as `[Source: filename#section]`

## Quick Start

```bash
# Start infrastructure
docker compose up -d

# Qdrant UI:  http://localhost:6333/dashboard
# Postgres:   localhost:5432 (db: ragdb)
# MinIO UI:   http://localhost:9001
# Redis:      localhost:6379

# Install dependencies
pip install -e .

# Pull the LLM model
ollama pull hf.co/unsloth/Qwen3-8B-GGUF:UD-Q4_K_XL

# Run ingestion on your docs
python -m services.ingestion.bulk_runner ./documents

# Start the API
uvicorn services.api.main:app --reload
```

## API

```bash
# Health check
curl http://localhost:8000/health

# Single-turn query
curl -X POST http://localhost:8000/query \
  -H 'Content-Type: application/json' \
  -d '{"query": "how does the chunker work?"}'

# Multi-turn conversation
curl -X POST http://localhost:8000/session
# {"session_id": "a1b2c3d4e5f6g7h8"}

curl -X POST http://localhost:8000/query \
  -H 'Content-Type: application/json' \
  -d '{"query": "how does the chunker work?", "session_id": "a1b2c3d4e5f6g7h8"}'

curl -X POST http://localhost:8000/query \
  -H 'Content-Type: application/json' \
  -d '{"query": "what about its performance?", "session_id": "a1b2c3d4e5f6g7h8"}'

# Streaming response
curl -X POST http://localhost:8000/query/stream \
  -H 'Content-Type: application/json' \
  -d '{"query": "explain the writer module"}'

# Trigger ingestion
curl -X POST http://localhost:8000/ingest?directory=./documents
```

## Project Structure

```
services/
  api/            FastAPI gateway + routes
  ingestion/      Parsers, chunker, embedder, writer, bulk runner
  query/          Session, rewriter, retriever, reranker, generator, cache, pipeline
shared/           Pydantic models, config, DB helpers
prompts/          Versioned system + rewrite prompts
documents/        Drop raw docs here for ingestion
```

## Configuration

Copy `.env.example` to `.env`. Key settings:

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_MODEL` | `hf.co/unsloth/Qwen3-8B-GGUF:UD-Q4_K_XL` | LLM model for generation |
| `EMBEDDING_MODEL` | `BAAI/bge-base-en-v1.5` | Embedding model (768-dim) |
| `RERANKER_MODEL` | `cross-encoder/ms-marco-MiniLM-L-6-v2` | Cross-encoder for reranking |
| `SESSION_TTL` | `7200` | Conversation session TTL in seconds |
| `CACHE_TTL` | `3600` | Query cache TTL in seconds |

## Build Phases

1. **Ingestion Pipeline** — parsers, chunker, embedder, writer, bulk runner (done)
2. **Query Pipeline** — hybrid retrieval, reranking, generation, caching, multi-turn (done)
3. **Quality + Eval** — test sets, metrics (Hit Rate, Faithfulness, MRR), guardrails
4. **Kubernetes** — Minikube/K3s, HPA, liveness probes
5. **Advanced** — long-term memory, multi-tenancy, streaming ingestion, model routing

## License

Private project.
