"""AI-owned tables (additive — migration 08). Shares the app's SQLAlchemy
Base/engine but never maps or alters an existing table (design rule 5)."""
import uuid

from sqlalchemy import JSON, Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class AIRun(Base):
    __tablename__ = "ai_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    agent_key = Column(String(50), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="queued", index=True)  # queued|running|completed|failed
    session_id = Column(String(100), nullable=True, index=True)
    input_summary = Column(Text, nullable=True)
    output_summary = Column(Text, nullable=True)
    error_code = Column(String(50), nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default="now()")
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)


class AIMessage(Base):
    __tablename__ = "ai_messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(String(100), nullable=False, index=True)
    run_id = Column(UUID(as_uuid=True), ForeignKey("ai_runs.id", ondelete="SET NULL"), nullable=True)
    item = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default="now()")


class AIMemory(Base):
    """Durable memory records (Memory Layer). One table, scoped rows —
    scope semantics live in app/ai/memory/, not in the schema."""

    __tablename__ = "ai_memories"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    scope = Column(String(20), nullable=False)
    scope_ref = Column(String(100), nullable=False)
    key = Column(String(100), nullable=True)
    content = Column(JSON, nullable=False)
    importance = Column(Float, nullable=False, default=0.0)
    expires_at = Column(DateTime(timezone=True), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default="now()")
    updated_at = Column(DateTime(timezone=True), server_default="now()")


class AIAgentState(Base):
    """Operational enable/disable flag per agent key (survives restarts and
    is shared across workers, unlike in-process registry state)."""

    __tablename__ = "ai_agent_state"

    agent_key = Column(String(50), primary_key=True)
    enabled = Column(Boolean, nullable=False, default=True)
    updated_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default="now()")


class AIUsage(Base):
    __tablename__ = "ai_usage"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id = Column(UUID(as_uuid=True), ForeignKey("ai_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    model = Column(String(100), nullable=True)
    requests = Column(Integer, nullable=False, default=0)
    input_tokens = Column(Integer, nullable=False, default=0)
    output_tokens = Column(Integer, nullable=False, default=0)
    total_tokens = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), server_default="now()", index=True)
