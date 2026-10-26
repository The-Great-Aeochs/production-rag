# Production RAG

A framework-free RAG service for technical documentation and Python code, with
FastAPI, Qdrant vector retrieval, PostgreSQL full-text search, cross-encoder
reranking, Ollama generation, Redis sessions/cache, and S3-compatible storage.

The production foundation adds authenticated corpus boundaries, scoped caching,
durable ingestion, recoverable document publication, and automated regression
checks. Capacity, quality, and availability must still be validated on your
representative corpus and deployment hardware.

## Website and workspace RBAC

`web/` contains a Next.js showcase, sample answers, optional capped live demo,
and Clerk-authenticated workspace dashboard. Database memberships enforce
member, editor, and admin permissions on the API, with an access audit trail.

```bash
cd web
cp .env.example .env.local
npm ci
npm run dev
```

Use Node.js 24. Empty credentials serve the showcase and prewritten examples;
private workspaces require configured login and a running backend. For Vercel,
set Root Directory to `web`. See [website deployment and RBAC](docs/website.md)
for Clerk setup, migration, roles, source connections, demo quotas, and costs.
[UI design notes](docs/ui-design.md) explain the interface and frontend structure.

## Architecture

```text
Bearer token → corpus-scoped API → session/rewrite → exact cache
                                              ↓ miss
                     embed → Qdrant + Postgres FTS → RRF → rerank → Ollama

Admin → Postgres job queue → corpus-locked worker → parse/chunk/embed
       → Postgres pending → Qdrant + S3 acknowledged writes → Postgres ready
```

Qdrant returns candidate IDs; Postgres supplies authorized, published content.
The keyword ranker is `ts_rank_cd`; it is not BM25. Conversation answers are never
cached. Cache keys include owner, filters, model/prompt settings, and corpus revision.

## Local setup

Requires Python 3.11–3.13, uv 0.11.2, Docker Compose for local infrastructure,
Ollama, and a running supported S3-compatible object store.

```bash
cp .env.example .env
# Edit .env: independent random tokens/passwords and S3 endpoint/credentials.
uv sync --locked --extra models --extra dev
docker compose up -d
uv run --extra models python -m scripts.migrate
mkdir -p documents/default
# Place documents under documents/default/.
ollama pull hf.co/unsloth/Qwen3-8B-GGUF:UD-Q4_K_XL
uv run --extra models python -m services.ingestion.worker
# In another terminal:
uv run --extra models uvicorn services.api.main:app
```

Set `RAG_ADMIN_TOKEN` and `RAG_API_TOKEN` in your shell to the separate tokens from
`.env`. The environment mapping format is `API_KEYS={"<token>":"default"}`.

```bash
curl -X POST http://localhost:8000/ingest \
  -H "Authorization: Bearer $RAG_ADMIN_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"corpus_id":"default"}'
# Returns 202 with a job_id. Poll GET /ingest/<job_id> with the admin token.

curl -X POST http://localhost:8000/query \
  -H "Authorization: Bearer $RAG_API_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"query":"How are retries handled?","use_cache":false}'
```

Use `POST /session` to create a token-owned conversation and pass `session_id` in
queries. Use `POST /query/stream` for SSE; a final `error` event means the response
is incomplete. `/health/live` is process liveness; `/health/ready` checks serving
readiness. `/metrics` requires the admin token.

The historical MinIO community repository is archived. Configure a supported
S3 service. An optional `docker-compose.object-store.yml` accepts a verified image
and command for local self-hosting; no unmaintained default image is selected.

## Verification

```bash
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
uv run --extra dev mypy
uv run --extra dev pytest -q
# Includes database integration tests when TEST_DATABASE_URL is set:
TEST_DATABASE_URL=postgresql://user:password@localhost/testdb uv run --extra dev pytest -q
```

Tests create isolated schemas. Use a disposable database. Postgres integration
covers retries, partial publication, tombstones, corpus isolation, and worker
locks; Qdrant local mode and an injectable S3 fake cover retrieval and faults.
CI runs Python 3.11–3.13, builds the runtime container, and checks the Next.js
production build, TypeScript, formatting, frontend tests, and dependency audit.

See [the operations guide](docs/production.md) for migrations, rollout, recovery,
load measurement, evaluation, and remaining production decisions.

## Maintenance workflow

Development uses the `main` branch. Run the required checks before pushing;
GitHub CI also validates every push. Create a branch or PR only when explicitly
requested.

Automatic dependency-update PRs are disabled to avoid creating extra branches.
Dependency security alerts remain enabled. Apply dependency changes explicitly,
update `uv.lock` or `web/package-lock.json` with them, and verify the full test
suite before pushing. Python updates must remain within the supported range.
