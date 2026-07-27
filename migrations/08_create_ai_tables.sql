-- Migration 08: AI Operating Layer tables (additive; see AI_LAYER_DESIGN.md)
-- Run after 07. Idempotent: safe to re-run.
-- No existing table is altered.

CREATE TABLE IF NOT EXISTS ai_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    agent_key VARCHAR(50) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'running', 'completed', 'failed')),
    session_id VARCHAR(100),
    input_summary TEXT,
    output_summary TEXT,
    error_code VARCHAR(50),
    error_message TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP WITH TIME ZONE,
    finished_at TIMESTAMP WITH TIME ZONE
);

CREATE TABLE IF NOT EXISTS ai_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id VARCHAR(100) NOT NULL,
    run_id UUID REFERENCES ai_runs(id) ON DELETE SET NULL,
    item JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ai_usage (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL REFERENCES ai_runs(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    model VARCHAR(100),
    requests INTEGER NOT NULL DEFAULT 0,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_ai_runs_user_id ON ai_runs(user_id);
CREATE INDEX IF NOT EXISTS idx_ai_runs_agent_key ON ai_runs(agent_key);
CREATE INDEX IF NOT EXISTS idx_ai_runs_status ON ai_runs(status);
CREATE INDEX IF NOT EXISTS idx_ai_runs_session_id ON ai_runs(session_id) WHERE session_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_ai_runs_created_at ON ai_runs(created_at);
CREATE INDEX IF NOT EXISTS idx_ai_messages_session_id ON ai_messages(session_id);
CREATE INDEX IF NOT EXISTS idx_ai_usage_run_id ON ai_usage(run_id);
CREATE INDEX IF NOT EXISTS idx_ai_usage_user_id ON ai_usage(user_id);
CREATE INDEX IF NOT EXISTS idx_ai_usage_created_at ON ai_usage(created_at);

COMMENT ON TABLE ai_runs IS 'One row per AI agent run (AI Operating Layer)';
COMMENT ON TABLE ai_messages IS 'DB-backed conversation state for session-enabled agents';
COMMENT ON TABLE ai_usage IS 'Token usage per run; feeds per-user daily quotas';
