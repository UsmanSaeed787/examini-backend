-- Migration 11: AI Memory Layer (additive)
-- Run after 10. Idempotent: safe to re-run. No existing table is altered.
-- Conversation transcripts stay in ai_messages; this table holds scoped
-- memory records (workflow/session/artifact/agent/short_term facts).

CREATE TABLE IF NOT EXISTS ai_memories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    scope VARCHAR(20) NOT NULL
        CHECK (scope IN ('workflow', 'session', 'conversation', 'artifact', 'agent', 'short_term', 'long_term')),
    scope_ref VARCHAR(100) NOT NULL,
    key VARCHAR(100),
    content JSONB NOT NULL,
    importance REAL NOT NULL DEFAULT 0,
    expires_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_ai_memories_lookup ON ai_memories(user_id, scope, scope_ref);
CREATE INDEX IF NOT EXISTS idx_ai_memories_expires_at ON ai_memories(expires_at) WHERE expires_at IS NOT NULL;

COMMENT ON TABLE ai_memories IS 'Scoped memory records (AI Memory Layer)';
