"""AI Operating Layer tables (ai_runs, ai_messages, ai_usage).

Executes the same SQL as backend/migrations/08_create_ai_tables.sql (the
file stays for anyone still on the SQL-editor workflow; it is idempotent,
so applying it both ways is harmless).

Revision ID: 0002_ai_tables
Revises: 0001_baseline
"""
from pathlib import Path

from alembic import op

revision = "0002_ai_tables"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None

_SQL_FILE = Path(__file__).resolve().parents[2] / "migrations" / "08_create_ai_tables.sql"


def upgrade() -> None:
    op.execute(_SQL_FILE.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ai_usage CASCADE")
    op.execute("DROP TABLE IF EXISTS ai_messages CASCADE")
    op.execute("DROP TABLE IF EXISTS ai_runs CASCADE")
