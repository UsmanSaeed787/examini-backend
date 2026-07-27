"""Agent Registry operational state (ai_agent_state).

Executes the same SQL as backend/migrations/10_create_agent_state.sql.

Revision ID: 0004_agent_state
Revises: 0003_assessment_workflows
"""
from pathlib import Path

from alembic import op

revision = "0004_agent_state"
down_revision = "0003_assessment_workflows"
branch_labels = None
depends_on = None

_SQL_FILE = Path(__file__).resolve().parents[2] / "migrations" / "10_create_agent_state.sql"


def upgrade() -> None:
    op.execute(_SQL_FILE.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ai_agent_state CASCADE")
