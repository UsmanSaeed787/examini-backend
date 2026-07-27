"""AI Memory Layer table (ai_memories).

Executes the same SQL as backend/migrations/11_create_ai_memories.sql.

Revision ID: 0005_ai_memories
Revises: 0004_agent_state
"""
from pathlib import Path

from alembic import op

revision = "0005_ai_memories"
down_revision = "0004_agent_state"
branch_labels = None
depends_on = None

_SQL_FILE = Path(__file__).resolve().parents[2] / "migrations" / "11_create_ai_memories.sql"


def upgrade() -> None:
    op.execute(_SQL_FILE.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ai_memories CASCADE")
