# Production RAG: contributor notes

The README, executable code, and migrations describe the current system.
Keep this file as a maintenance guide; do not duplicate schemas or speculative
implementations here.

## Architecture

- `services/api/`: FastAPI routes, request limits, health, and metrics.
- `services/ingestion/`: Markdown, Python, and PDF parsers; structural chunking;
  embedding; durable Postgres jobs; recoverable publication.
- `services/query/`: session handling, rewriting, scoped cache, hybrid retrieval,
  reranking, and Ollama generation.
- `services/eval/`: retrieval metrics and optional end-to-end judging.
- `shared/`: validated configuration, data models, stores, identity, and RBAC.
- `web/`: separately deployed Next.js website and workspace UI. Read
  `web/AGENTS.md` and the installed Next.js guides before changing it.
- `migrations/`, `prompts/`: packaged, versioned SQL and prompt resources.

Postgres provides full-text ranking through `ts_rank_cd`; it is not BM25.
Qdrant supplies vector candidate IDs, and Postgres supplies authorized,
published content. Redis stores sessions, caches, and request limits. Postgres
owns the ingestion queue; there is no Celery queue. Configure a supported
S3-compatible object store separately.

## Implementation rules

- Keep the RAG pipeline framework-free: no LangChain or LlamaIndex abstractions.
- Preserve document structure, section origins, and parent relationships when
  chunking. Split oversized sections within configured token limits.
- Use semantic and keyword retrieval with matching corpus/metadata filters.
  Merge with Reciprocal Rank Fusion and rerank with the cross-encoder.
- Generate only from retrieved context, cite `[Source: filename#section]`, and
  acknowledge when context is insufficient. Keep prompts in `prompts/`.
- Run representative evaluations when changing chunking, embeddings, prompts,
  or retrieval. Change pinned model revisions together with their model names.
- Bound downstream calls and make failure behavior explicit. Preserve safe
  retrieval/rewrite fallbacks; authorization, quotas, and rate limits fail closed.
- Never present a synthetic smoke test or an unmeasured target as production
  capacity, availability, latency, cost, or customer-domain quality.

## Security and consistency

- Service keys map to configured corpora. User login verifies the configured
  RS256 issuer, audience, expiry, and subject against trusted JWKS.
- Postgres workspace memberships grant member, editor, and admin permissions.
  Browser role claims do not grant access. Platform admin secrets stay separate.
- Check membership on each protected request. Membership versions scope cache
  and session ownership; revocation/re-addition must not restore old sessions.
- Enforce corpus and published-document boundaries on both retrieval paths.
- Use exact, scoped, versioned cache keys including corpus revision. Never
  restore rounded-vector hash caching. Conversation answers are not cached.
- Ingestion runs under corpus advisory locks. Pending/deleting documents remain
  hidden until publication or cleanup completes. External stores do not share
  a distributed transaction; retain repair state after partial failures.
- Keep content-hash idempotency, retries, and deletion tombstones intact.
- Apply migrations with `python -m scripts.migrate` before updating services;
  API replicas check schema readiness and do not mutate the schema at startup.
- Keep secrets out of source, browser bundles, and logs. Full query-content
  logging is disabled by default. Public inference is opt-in, uses a dedicated
  public corpus, and has shared Redis quotas.

## Local verification

Follow `README.md` and `.env.example` for infrastructure, models, and credentials.
Use Python 3.11–3.13 with the committed uv lockfile:

```bash
uv sync --locked --extra dev
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
uv run --extra dev mypy
uv run --extra dev pytest -q
uv build
```

Set `TEST_DATABASE_URL` to a disposable Postgres database for integration tests;
tests create isolated schemas. `TEST_QDRANT_URL` enables server-backed Qdrant
checks. CI runs all supported Python versions and builds the runtime image.

For the website, use Node.js 24 and run from `web/`:

```bash
npm ci
npm run typecheck
npm test
npm run format:check
npm run build
```

Preserve keyboard operation, source disclosures, explicit service states,
workspace-switch cancellation, safe Markdown, and role boundaries during UI
refactors. Keep shared request handling and types outside presentation views.

## Guides and Git conventions

- `docs/production.md`: rollout, backups, recovery, load, and evaluation.
- `docs/website.md`: Vercel, Clerk, source connections, demo limits, and RBAC.
- `docs/ui-design.md`: design decisions and frontend organization.
- Use descriptive branches and `feat:`, `fix:`, `refactor:`, `eval:`, `infra:`, or
  `docs:` commit prefixes. Keep validation and deployment limits in PR descriptions.
- Tag explicit phase milestones using the existing `v0.1.0-phase1` pattern;
  routine cleanup is not a phase release.
