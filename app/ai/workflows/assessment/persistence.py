"""Workflow tables (additive — migration 09). Same conventions as the ai_*
tables: shared Base, no existing table touched."""
import uuid

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class AIWorkflow(Base):
    __tablename__ = "ai_workflows"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = Column(String(30), nullable=False, default="assessment")
    class_id = Column(UUID(as_uuid=True), ForeignKey("classes.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(255), nullable=False)
    state = Column(String(20), nullable=False, default="draft", index=True)
    current_stage = Column(String(50), nullable=True)
    approval_mode = Column(String(20), nullable=False, default="every_stage")
    config = Column(JSON, nullable=False, default=dict)
    result = Column(JSON, nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default="now()")
    updated_at = Column(DateTime(timezone=True), server_default="now()")
    finished_at = Column(DateTime(timezone=True), nullable=True)


class AIWorkflowStage(Base):
    __tablename__ = "ai_workflow_stages"
    __table_args__ = (UniqueConstraint("workflow_id", "stage_key", name="uq_workflow_stage"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id = Column(UUID(as_uuid=True), ForeignKey("ai_workflows.id", ondelete="CASCADE"), nullable=False, index=True)
    stage_key = Column(String(50), nullable=False)
    sequence = Column(Integer, nullable=False)
    status = Column(String(20), nullable=False, default="pending")
    revision = Column(Integer, nullable=False, default=1)
    artifact = Column(JSON, nullable=True)
    notes = Column(Text, nullable=True)
    # Populated when a stage is executed by an agent (AgentStageHandler).
    run_id = Column(UUID(as_uuid=True), ForeignKey("ai_runs.id", ondelete="SET NULL"), nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)


class AIWorkflowCheckpoint(Base):
    __tablename__ = "ai_workflow_checkpoints"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id = Column(UUID(as_uuid=True), ForeignKey("ai_workflows.id", ondelete="CASCADE"), nullable=False, index=True)
    stage_key = Column(String(50), nullable=False)
    revision = Column(Integer, nullable=False, default=1)
    decision = Column(String(10), nullable=False)  # approved | rejected
    decided_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default="now()")


class AIWorkflowGeneration(Base):
    """One materialization attempt: approved plan -> generated questions ->
    draft exam -> (human) publish. Migration 12.

    The exam content itself lives in `exams`/`questions` and is written only
    through ExamService; this row is the audit link and never duplicates it."""

    __tablename__ = "ai_workflow_generations"
    __table_args__ = (
        UniqueConstraint("workflow_id", "attempt", name="uq_workflow_generation_attempt"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id = Column(UUID(as_uuid=True), ForeignKey("ai_workflows.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    # SET NULL: deleting a draft exam must not erase the audit record.
    exam_id = Column(UUID(as_uuid=True), ForeignKey("exams.id", ondelete="SET NULL"), nullable=True, index=True)
    run_id = Column(UUID(as_uuid=True), ForeignKey("ai_runs.id", ondelete="SET NULL"), nullable=True)
    status = Column(String(20), nullable=False, default="pending")
    attempt = Column(Integer, nullable=False, default=1)
    question_count = Column(Integer, nullable=False, default=0)
    findings = Column(JSON, nullable=False, default=list)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default="now()")
    generated_at = Column(DateTime(timezone=True), nullable=True)
    published_at = Column(DateTime(timezone=True), nullable=True)
