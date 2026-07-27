-- Migration 10: Agent Registry operational state (additive)
-- Run after 09. Idempotent: safe to re-run. No existing table is altered.

CREATE TABLE IF NOT EXISTS ai_agent_state (
    agent_key VARCHAR(50) PRIMARY KEY,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    updated_by UUID REFERENCES users(id) ON DELETE SET NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE ai_agent_state IS 'Enable/disable flags per AI agent key (Agent Registry)';
