"""Alembic environment — wired to the app's own engine and metadata.

Uses app.database.engine (built from DATABASE_URL in backend/.env), so no
connection string is duplicated in alembic.ini. target_metadata imports all
model modules so future `alembic revision --autogenerate` sees the full
schema (existing tables + the AI layer's ai_* tables).
"""
from logging.config import fileConfig

from alembic import context

from app.database import Base, engine

# Import every model module so Base.metadata is fully populated.
import app.models  # noqa: F401  (users, classes, exams, attempts, materials, ...)
import app.ai.persistence.models  # noqa: F401  (ai_runs, ai_messages, ai_usage)
import app.ai.workflows.assessment.persistence  # noqa: F401  (ai_workflows, stages, checkpoints)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of executing (alembic upgrade --sql)."""
    context.configure(
        url=str(engine.url),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
