# Operations and rollout

## Boundaries and known limits

This release establishes correctness and operational controls. It does not certify
production capacity or answer quality. Benchmark with representative data before
setting an SLO. Service keys are scoped to one corpus; signed-in Clerk users have
database-enforced workspace memberships and roles. Per-document ACLs and enterprise
SSO provisioning are not implemented. An admin token is privileged across corpora. Store keys in a
secret manager, expose the API through TLS, and keep data stores private. In
production set ENVIRONMENT=production; credentials, TLS to S3, and separate admin
and query keys become mandatory. Configure encrypted transports to Postgres (PG_SSLMODE/PG_SSLROOTCERT),
Redis (rediss://), and Qdrant (https://) for your network requirements.

Query/answer logging is off. Opting into LOG_QUERY_CONTENT requires an explicit
retention and privacy policy. Prometheus HTTP labels use route templates, not
queries, source paths, or session IDs. Capture application logs and scrape
/metrics with the admin bearer token. Establish alerts from measured baselines
for error ratios, p95, queue age, failed jobs, replica readiness and store capacity.
The current metrics endpoint provides HTTP counts and latency; ingestion/model
stage metrics and distributed tracing remain follow-up work.

## Upgrade an existing installation

1. Stop API and ingestion processes. Back up Postgres and the object store, and
   snapshot Qdrant. Preserve the old application image and configuration.
2. Install the locked dependencies and run `python -m scripts.migrate` once as a
   release task with database DDL permissions. API replicas never change schema.
   Migrations serialize with an advisory transaction lock and run transactionally.
3. Assign existing documents to the `default` corpus. Their migration default is
   `default`; their empty pipeline version deliberately triggers a full reindex.
   Put the complete source tree under INGEST_ROOT/default, set separate bearer
   tokens, and configure a supported S3 endpoint and scoped service credentials.
4. Run the worker and enqueue a full default-corpus snapshot. Wait for completion.
   This also rewrites old vector payloads with corpus filters. Until reindexing
   finishes, old vectors without a corpus field cannot participate in semantic
   search; keyword retrieval remains available for ready legacy chunks.
5. Start the API, confirm /health/ready and authenticated query/stream behavior,
   then gradually admit traffic. Old 16-character sessions are deliberately
   invalidated by the new 32-character session/ownership contract.

The migration is additive except that source-path uniqueness becomes corpus+path.
Do not roll the old API back onto a database serving multiple corpora: old code
has no isolation enforcement. Restore the old data snapshot alongside the old
image, or roll forward with a fix. Keep old raw object keys until successful
reindexing and retention approval; new objects use corpus_id/source_path.

## Durable ingestion and failure recovery

The queue is in Postgres, so Redis loss cannot discard an accepted ingestion job.
One dedicated connection holds a session advisory lock per corpus. Different
corpora run in parallel; the same corpus is serialized across workers. After a
crash, the database releases the connection's lock and another worker resumes
the processing job. Attempts use exponential retry delays and become failed at
INGESTION_MAX_ATTEMPTS. Inspect GET /ingest/<job_id>, correct the underlying issue,
and submit a new job. Every retry rescans; already-published matching documents
are skipped. Job counters describe the latest attempt.

Each job snapshots its entire configured corpus root. Subdirectory snapshots,
outside-root paths, escaping symlinks, and oversized source files are rejected.
Keep source snapshots stable while jobs run. Empty snapshots cannot erase an
existing corpus; a deliberate full-corpus purge needs a separate administrative
procedure. This release handles local source trees, not untrusted file uploads.

Publication is deliberately availability-reducing during failures: a pending or
deleting document is hidden until all required external operations succeed.
Postgres stores this repair state before external writes. Qdrant writes wait for
acknowledgment. Binary files retain their original bytes in S3. Versioned chunk
IDs and database hydration reject orphan/stale vector candidates. These are
recoverable operations, not a distributed transaction across three databases.

Back up Postgres and S3 at compatible recovery points. Qdrant can be rebuilt from
source documents by reindexing. Exercise a restore in a separate environment:
restore stores, run migrations, requeue ingestion to reconcile pending documents,
then test sources, citations, counts, deleted-document exclusion, and corpus
isolation. Decide RPO/RTO from actual business needs; no recovery time is claimed.

## Serving and scaling

Start with one API process per replica: each process owns local embedding and
reranking models. Multiple Uvicorn workers multiply model memory. Admission is
bounded per process; Redis enforces per-token requests/minute across replicas.
429 indicates token rate limits, 503 indicates capacity or dependency failures.
Concurrent queries for one session receive 409. Conversation turns are committed
atomically only while the token ownership and Redis lease still match.
Both retrieval legs share a deadline, and outstanding retrieval tasks are bounded
including after callers time out. Network, database statement and pool limits
prevent indefinite waits. Generation limits tokens; streaming has an overall
timeout. Nonstreaming HTTP timeouts bound I/O inactivity rather than a hard
end-to-end wall clock. Cancelled HTTP calls may leave bounded local model work
running until the model call returns.

Size Postgres connection capacity for replica_count × PG_POOL_MAX_SIZE plus
workers, migrations and monitoring. Keep Qdrant and API in the same region.
Use replicated/managed Postgres, Redis, S3 and Qdrant for availability; this Compose
file is local development only. API, ingestion workers and inference should scale
independently. Move embeddings/reranking to dedicated inference services when
load or memory measurements justify the interface change. CPU Torch is locked
for Linux; GPU images need an explicitly tested CUDA/PyTorch variant.

Build with `docker build -t production-rag:0.3.0 .`. Run migrations from that same
image before starting replicas. For Compose app mode, build and run a release
command first: `docker compose --profile app run --rm api python -m scripts.migrate`,
then `docker compose --profile app up -d`. Host Ollama must accept connections from
containers; set OLLAMA_HOST and firewall access deliberately. Configure
CONTAINER_S3_ENDPOINT for the chosen service. The optional object-store override
uses MinIO-style arguments/variables; adapt them for the selected implementation.
Prewarm/download models before allowing production readiness. Cache model files
on writable volumes when running with a read-only root filesystem.

## Evaluation and capacity evidence

The checked-in v1 dataset is a 12-question synthetic smoke test about this code's
behavior, not evidence of customer-domain quality. Copy its fixture files into a
separate evaluation corpus and index them:

```bash
mkdir -p documents/eval
cp services/eval/fixtures/corpus/*.md documents/eval/
python -m services.ingestion.bulk_runner --corpus eval
# A worker must process the returned job before evaluation.
python -m scripts.run_eval --mode retrieval
python -m scripts.run_eval --mode e2e --judge-provider ollama
```

The eval CLI exits nonzero for failed or missing critical metrics. Results include
source commit and configuration. Existing thresholds (hit rate .85, MRR .70,
faithfulness .90) are targets, not attained results. Use a held-out dataset with
real labeled relevance, citations, negatives, ambiguous questions, code identifiers,
multi-turn follow-ups and malicious retrieved text. Calibrate model judges with
human review. Negative/clarification behavior needs dedicated metrics; the current
aggregate retrieval metrics are most useful for answerable questions. Run evals
when chunking, embeddings, filters, prompts or ranking change. In particular,
compare embedding tokenizer limits against chunk sizes before indexing real
corpora; the current chunker still uses cl100k token counts, not the BGE tokenizer.

Use separate evaluation tenants. Never run load probes against production by
accident. Set a benchmark token's rate limit to the intended test workload and use
a JSON list of representative questions:

```bash
RAG_API_TOKEN=<benchmark-token> python -m scripts.benchmark \
  --queries queries.json --requests 100 --concurrency 4
# Repeat with --use-cache for an explicitly separate cache workload.
```

Record corpus document/chunk counts, model versions/revisions, CPU/GPU/RAM, replica counts,
error ratios, p50/p95, throughput, token usage/cost and ingestion duration. This
probe reports successful-query latency separately from errors, and fails if any
request fails. It measures a bounded closed-loop workload, not an open-loop
arrival process or a full saturation test. Add an arrival-rate load tool once the
target traffic distribution is known. Keep uncached and cached results separate.

Before expanding rollout: validate domain quality, load tests, real Qdrant/S3
integration, restoration, token revocation, prompt-injection containment, and a
staged deployment/rollback drill. Hosting choice, SLO/RPO/RTO, production identity,
per-document permissions, long-term retention, and GPU serving remain explicit
platform decisions.

## References

- [Microsoft RAG design and evaluation](https://learn.microsoft.com/en-us/azure/architecture/ai-ml/guide/rag/rag-solution-design-and-evaluation-guide)
- [Qdrant multitenancy](https://qdrant.tech/documentation/guides/multitenancy/)
- [OWASP LLM application risks](https://genai.owasp.org/llm-top-10/)
- [MinIO maintenance notice](https://github.com/minio/minio)
