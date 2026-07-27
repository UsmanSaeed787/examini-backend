-- Migration 09: Assessment Intelligence workflow tables (additive)
-- Run after 08. Idempotent: safe to re-run. No existing table is altered.

CREATE TABLE IF NOT EXISTS ai_workflows (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind VARCHAR(30) NOT NULL DEFAULT 'assessment',
    class_id UUID NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
    title VARCHAR(255) NOT NULL,
    state VARCHAR(20) NOT NULL DEFAULT 'draft'
        CHECK (state IN ('draft', 'in_progress', 'awaiting_approval', 'completed', 'cancelled', 'failed')),
    current_stage VARCHAR(50),
    approval_mode VARCHAR(20) NOT NULL DEFAULT 'every_stage'
        CHECK (approval_mode IN ('every_stage', 'final_only', 'none')),
    config JSONB NOT NULL DEFAULT '{}'::jsonb,
    result JSONB,
    error TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMP WITH TIME ZONE
);

CREATE TABLE IF NOT EXISTS ai_workflow_stages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workflow_id UUID NOT NULL REFERENCES ai_workflows(id) ON DELETE CASCADE,
    stage_key VARCHAR(50) NOT NULL,
    sequence INTEGER NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'in_review', 'approved', 'rejected', 'failed')),
    revision INTEGER NOT NULL DEFAULT 1,
    artifact JSONB,
    notes TEXT,
    run_id UUID REFERENCES ai_runs(id) ON DELETE SET NULL,
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    CONSTRAINT uq_workflow_stage UNIQUE (workflow_id, stage_key)
);

CREATE TABLE IF NOT EXISTS ai_workflow_checkpoints (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workflow_id UUID NOT NULL REFERENCES ai_workflows(id) ON DELETE CASCADE,
    stage_key VARCHAR(50) NOT NULL,
    revision INTEGER NOT NULL DEFAULT 1,
    decision VARCHAR(10) NOT NULL CHECK (decision IN ('approved', 'rejected')),
    decided_by UUID REFERENCES users(id) ON DELETE SET NULL,
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_ai_workflows_user_id ON ai_workflows(user_id);
CREATE INDEX IF NOT EXISTS idx_ai_workflows_state ON ai_workflows(state);
CREATE INDEX IF NOT EXISTS idx_ai_workflows_class_id ON ai_workflows(class_id);
CREATE INDEX IF NOT EXISTS idx_ai_workflow_stages_workflow_id ON ai_workflow_stages(workflow_id);
CREATE INDEX IF NOT EXISTS idx_ai_workflow_checkpoints_workflow_id ON ai_workflow_checkpoints(workflow_id);

COMMENT ON TABLE ai_workflows IS 'Assessment Intelligence workflow instances (AI Operating Layer)';
COMMENT ON TABLE ai_workflow_stages IS 'Per-stage status, revision, and produced artifact';
COMMENT ON TABLE ai_workflow_checkpoints IS 'Human approval decisions at stage checkpoints';
