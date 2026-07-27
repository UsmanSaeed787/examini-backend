"""Assessment Intelligence workflow tables.

Executes the same SQL as backend/migrations/09_create_assessment_workflow_tables.sql
(idempotent; kept in both places like migration 08).

Revision ID: 0003_assessment_workflows
Revises: 0002_ai_tables
"""
from pathlib import Path

from alembic import op

revision = "0003_assessment_workflows"
down_revision = "0002_ai_tables"
branch_labels = None
depends_on = None

_SQL_FILE = (
    Path(__file__).resolve().parents[2]
    / "migrations"
    / "09_create_assessment_workflow_tables.sql"
)


def upgrade() -> None:
    op.execute(_SQL_FILE.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ai_workflow_checkpoints CASCADE")
    op.execute("DROP TABLE IF EXISTS ai_workflow_stages CASCADE")
    op.execute("DROP TABLE IF EXISTS ai_workflows CASCADE")
