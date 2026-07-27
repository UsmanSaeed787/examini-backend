"""Allow 'adjusted' as a checkpoint decision.

Executes the same SQL as backend/migrations/13_allow_adjusted_checkpoints.sql.

Revision ID: 0007_adjusted_checkpoints
Revises: 0006_workflow_generations
"""
from pathlib import Path

from alembic import op

revision = "0007_adjusted_checkpoints"
down_revision = "0006_workflow_generations"
branch_labels = None
depends_on = None

_SQL_FILE = (
    Path(__file__).resolve().parents[2]
    / "migrations"
    / "13_allow_adjusted_checkpoints.sql"
)


def upgrade() -> None:
    op.execute(_SQL_FILE.read_text(encoding="utf-8"))


def downgrade() -> None:
    # Existing 'adjusted' rows would violate the narrower constraint, so clear
    # them to the closest historical equivalent before restoring it.
    op.execute(
        "UPDATE ai_workflow_checkpoints SET decision = 'rejected' WHERE decision = 'adjusted'"
    )
    op.execute(
        "ALTER TABLE ai_workflow_checkpoints "
        "DROP CONSTRAINT IF EXISTS ai_workflow_checkpoints_decision_check"
    )
    op.execute(
        "ALTER TABLE ai_workflow_checkpoints "
        "ADD CONSTRAINT ai_workflow_checkpoints_decision_check "
        "CHECK (decision IN ('approved', 'rejected'))"
    )
