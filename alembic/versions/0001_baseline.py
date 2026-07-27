"""Baseline: schema as created by hand-run SQL migrations 01-07.

This revision is intentionally a no-op. The pre-Alembic schema (users,
classes, exams, attempts, materials, student_profiles, ...) was created by
executing backend/migrations/01..07 manually; on a database where those have
been run, upgrading through this revision changes nothing. A brand-new
database must still run 01-07 first (they remain the bootstrap source of
truth), then `alembic upgrade head`.

Revision ID: 0001_baseline
Revises:
"""
revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
