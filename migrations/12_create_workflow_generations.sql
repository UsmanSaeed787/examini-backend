-- Migration 12: Assessment materialization attempts (additive)
-- Run after 11. Idempotent: safe to re-run. No existing table is altered.
--
-- One row per generation ATTEMPT for an assessment workflow, so the journey
-- from an approved AssessmentPlan to a published exam is fully auditable:
-- which run produced the questions, what the deterministic validation said,
-- which exam row it became, and when a human published it.
--
-- The exam itself lives in the existing `exams` table and is written only
-- through ExamService — this table never duplicates exam content.

CREATE TABLE IF NOT EXISTS ai_workflow_generations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workflow_id UUID NOT NULL REFERENCES ai_workflows(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    -- SET NULL (not CASCADE): deleting a draft exam must not erase the audit
    -- record that it was generated.
    exam_id UUID REFERENCES exams(id) ON DELETE SET NULL,
    run_id UUID REFERENCES ai_runs(id) ON DELETE SET NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    attempt INTEGER NOT NULL DEFAULT 1,
    question_count INTEGER NOT NULL DEFAULT 0,
    findings JSON NOT NULL DEFAULT '[]',
    error TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    generated_at TIMESTAMP WITH TIME ZONE,
    published_at TIMESTAMP WITH TIME ZONE,
    CONSTRAINT uq_workflow_generation_attempt UNIQUE (workflow_id, attempt)
);

CREATE INDEX IF NOT EXISTS idx_ai_workflow_generations_workflow
    ON ai_workflow_generations(workflow_id);
CREATE INDEX IF NOT EXISTS idx_ai_workflow_generations_user
    ON ai_workflow_generations(user_id);
CREATE INDEX IF NOT EXISTS idx_ai_workflow_generations_exam
    ON ai_workflow_generations(exam_id);

COMMENT ON TABLE ai_workflow_generations IS
    'Materialization attempts turning an approved AssessmentPlan into an exam';
COMMENT ON COLUMN ai_workflow_generations.status IS
    'pending | generating | generated | published | failed | superseded';
COMMENT ON COLUMN ai_workflow_generations.findings IS
    'Deterministic validation findings recorded against the generated questions';
