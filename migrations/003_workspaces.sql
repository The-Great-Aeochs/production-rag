ALTER TABLE corpora ADD COLUMN IF NOT EXISTS display_name TEXT NOT NULL DEFAULT '';
ALTER TABLE corpora ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
CREATE TABLE IF NOT EXISTS app_users (
    user_id TEXT PRIMARY KEY,
    issuer TEXT NOT NULL,
    subject TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(issuer, subject)
);
CREATE TABLE IF NOT EXISTS workspace_memberships (
    corpus_id TEXT NOT NULL REFERENCES corpora(corpus_id),
    user_id TEXT NOT NULL REFERENCES app_users(user_id),
    role TEXT NOT NULL CHECK(role IN ('member','editor','admin')),
    version BIGINT NOT NULL DEFAULT 1,
    revoked_at TIMESTAMPTZ,
    PRIMARY KEY(corpus_id, user_id)
);
CREATE INDEX IF NOT EXISTS memberships_user ON workspace_memberships(user_id) WHERE revoked_at IS NULL;
CREATE TABLE IF NOT EXISTS authorization_audit (
    event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    corpus_id TEXT NOT NULL REFERENCES corpora(corpus_id),
    actor_id TEXT NOT NULL,
    target_id TEXT,
    action TEXT NOT NULL,
    role TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS authorization_audit_workspace ON authorization_audit(corpus_id, created_at DESC);
