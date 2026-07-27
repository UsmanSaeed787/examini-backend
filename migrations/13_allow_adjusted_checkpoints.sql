-- Migration 13: record deterministic mix adjustments as checkpoint decisions
-- Run after 12. Idempotent: safe to re-run. No data is altered or removed.
--
-- A teacher can now change the question mix without asking the AI to redesign
-- ("adjust" rather than "reject"). That is a third kind of decision at a
-- checkpoint and belongs in the same audit trail, so the CHECK constraint has
-- to admit it.

ALTER TABLE ai_workflow_checkpoints
    DROP CONSTRAINT IF EXISTS ai_workflow_checkpoints_decision_check;

ALTER TABLE ai_workflow_checkpoints
    ADD CONSTRAINT ai_workflow_checkpoints_decision_check
    CHECK (decision IN ('approved', 'rejected', 'adjusted'));

COMMENT ON COLUMN ai_workflow_checkpoints.decision IS
    'approved | rejected (AI re-runs) | adjusted (teacher changed the mix, deterministic recompute)';
