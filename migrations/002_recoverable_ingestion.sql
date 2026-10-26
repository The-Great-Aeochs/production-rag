CREATE TABLE IF NOT EXISTS corpora (
    corpus_id TEXT PRIMARY KEY,
    revision BIGINT NOT NULL DEFAULT 0
);
INSERT INTO corpora(corpus_id) VALUES ('default') ON CONFLICT DO NOTHING;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS corpus_id TEXT NOT NULL DEFAULT 'default';
ALTER TABLE documents ADD COLUMN IF NOT EXISTS sync_status TEXT NOT NULL DEFAULT 'ready';
ALTER TABLE documents ADD COLUMN IF NOT EXISTS pipeline_version TEXT NOT NULL DEFAULT '';
ALTER TABLE documents DROP CONSTRAINT IF EXISTS documents_source_path_key;
CREATE UNIQUE INDEX IF NOT EXISTS documents_corpus_path ON documents(corpus_id, source_path);
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS corpus_id TEXT NOT NULL DEFAULT 'default';
CREATE INDEX IF NOT EXISTS chunks_corpus_id ON chunks(corpus_id);
ALTER TABLE ingestion_jobs ADD COLUMN IF NOT EXISTS corpus_id TEXT NOT NULL DEFAULT 'default';
ALTER TABLE ingestion_jobs ADD COLUMN IF NOT EXISTS directory TEXT;
ALTER TABLE ingestion_jobs ADD COLUMN IF NOT EXISTS attempts INT NOT NULL DEFAULT 0;
ALTER TABLE ingestion_jobs ADD COLUMN IF NOT EXISTS next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
ALTER TABLE ingestion_jobs ADD COLUMN IF NOT EXISTS last_error TEXT;
ALTER TABLE ingestion_jobs ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
CREATE INDEX IF NOT EXISTS ingestion_jobs_queue ON ingestion_jobs(next_attempt_at, created_at)
    WHERE status IN ('pending', 'processing');
