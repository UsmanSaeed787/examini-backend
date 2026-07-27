"""Assessment materialization attempts (ai_workflow_generations).

Executes the same SQL as backend/migrations/12_create_workflow_generations.sql.

Revision ID: 0006_workflow_generations
Revises: 0005_ai_memories
"""
from pathlib import Path

from alembic import op

revision = "0006_workflow_generations"
down_revision = "0005_ai_memories"
branch_labels = None
depends_on = None

_SQL_FILE = (
    Path(__file__).resolve().parents[2]
    / "migrations"
    / "12_create_workflow_generations.sql"
)


def upgrade() -> None:
    op.execute(_SQL_FILE.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ai_workflow_generations CASCADE")
