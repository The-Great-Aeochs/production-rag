CREATE TABLE IF NOT EXISTS documents (
    doc_id          TEXT PRIMARY KEY,
    source_path     TEXT UNIQUE NOT NULL,
    doc_type        TEXT NOT NULL,
    language        TEXT,
    raw_content     TEXT,
    metadata        JSONB DEFAULT '{}',
    content_hash    TEXT NOT NULL,
    embedding_model TEXT NOT NULL,
    ingested_at     TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS chunks (
    chunk_id        TEXT PRIMARY KEY,
    doc_id          TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    content         TEXT NOT NULL,
    token_count     INT NOT NULL,
    chunk_index     INT NOT NULL,
    parent_chunk_id TEXT,
    section_path    TEXT[] DEFAULT '{}',
    source_path     TEXT NOT NULL,
    doc_type        TEXT NOT NULL,
    language        TEXT,
    metadata        JSONB DEFAULT '{}',
    embedding_model TEXT NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    search_vector   TSVECTOR
);

-- Trigger to keep search_vector in sync on insert/update
CREATE OR REPLACE FUNCTION chunks_search_vector_update() RETURNS trigger AS $$
BEGIN
    NEW.search_vector :=
        setweight(to_tsvector('english', coalesce(NEW.source_path, '')), 'A') ||
        setweight(to_tsvector('english', coalesce(array_to_string(NEW.section_path, ' '), '')), 'B') ||
        setweight(to_tsvector('english', coalesce(NEW.content, '')), 'C');
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS chunks_search_vector_trigger ON chunks;
CREATE TRIGGER chunks_search_vector_trigger
    BEFORE INSERT OR UPDATE ON chunks
    FOR EACH ROW EXECUTE FUNCTION chunks_search_vector_update();

CREATE INDEX IF NOT EXISTS idx_chunks_doc_id ON chunks(doc_id);
CREATE INDEX IF NOT EXISTS idx_chunks_source_path ON chunks(source_path);
CREATE INDEX IF NOT EXISTS idx_chunks_search_vector ON chunks USING GIN(search_vector);
CREATE INDEX IF NOT EXISTS idx_chunks_metadata ON chunks USING GIN(metadata);
CREATE INDEX IF NOT EXISTS idx_documents_content_hash ON documents(content_hash);

CREATE TABLE IF NOT EXISTS query_logs (
    log_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    query_text      TEXT NOT NULL,
    filters         JSONB,
    retrieved_chunks JSONB,
    reranked_chunks JSONB,
    answer          TEXT,
    model_used      TEXT,
    prompt_version  TEXT,
    latency_ms      JSONB,
    cache_hit       BOOLEAN DEFAULT FALSE,
    user_feedback   TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_query_logs_created ON query_logs(created_at DESC);

CREATE TABLE IF NOT EXISTS ingestion_jobs (
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
