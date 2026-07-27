"""Shared DB-session scope for the AI layer.

The tool execution pipeline lives in registry.py (Phase 3); this module keeps
only the session helper, which is also the default injected
ToolDependencies.session_scope and the scope used by workflow stage handlers
and the facade's deterministic helpers."""
from contextlib import contextmanager

from app.database import SessionLocal


@contextmanager
def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
