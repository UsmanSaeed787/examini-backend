from sqlalchemy import Column, String, Integer, Boolean, DateTime, ForeignKey, Numeric
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from app.database import Base
import uuid


class ExamAttempt(Base):
    __tablename__ = "exam_attempts"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    exam_id = Column(UUID(as_uuid=True), ForeignKey("exams.id", ondelete="CASCADE"), nullable=False, index=True)
    student_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    started_at = Column(DateTime(timezone=True), server_default='now()')
    submitted_at = Column(DateTime(timezone=True))
    status = Column(String(20), default="in_progress", index=True)
    time_spent_minutes = Column(Integer)
    attempt_number = Column(Integer, default=1)
    
    # Relationships
    exam = relationship("Exam", back_populates="attempts")
    student = relationship("User", back_populates="exam_attempts")
    responses = relationship("ExamResponse", back_populates="attempt", cascade="all, delete-orphan")
    result = relationship("ExamResult", back_populates="attempt", uselist=False, cascade="all, delete-orphan")


class ExamResponse(Base):
    __tablename__ = "exam_responses"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    attempt_id = Column(UUID(as_uuid=True), ForeignKey("exam_attempts.id", ondelete="CASCADE"), nullable=False, index=True)
    question_id = Column(UUID(as_uuid=True), ForeignKey("questions.id", ondelete="CASCADE"), nullable=False, index=True)
    answer_text = Column(String)
    selected_options = Column(ARRAY(UUID))
    is_correct = Column(Boolean)
    points_earned = Column(Numeric(5, 2), default=0)
    answered_at = Column(DateTime(timezone=True), server_default='now()')
    
    # Relationships
    attempt = relationship("ExamAttempt", back_populates="responses")
    question = relationship("Question", back_populates="responses")


class ExamResult(Base):
    __tablename__ = "exam_results"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    attempt_id = Column(UUID(as_uuid=True), ForeignKey("exam_attempts.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    total_score = Column(Numeric(10, 2), nullable=False)
    max_score = Column(Numeric(10, 2), nullable=False)
    percentage = Column(Numeric(5, 2), nullable=False, index=True)
    grade = Column(String(10))
    passed = Column(Boolean)
    reviewed_at = Column(DateTime(timezone=True))
    reviewed_by = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    feedback = Column(String)
    created_at = Column(DateTime(timezone=True), server_default='now()')
    
    # Relationships
    attempt = relationship("ExamAttempt", back_populates="result")
    reviewer = relationship("User")


class ExamPermission(Base):
    __tablename__ = "exam_permissions"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    exam_id = Column(UUID(as_uuid=True), ForeignKey("exams.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    can_view_results = Column(Boolean, default=True)
    results_visible_to = Column(String(20), default="all")
    visible_from_date = Column(DateTime(timezone=True))
    auto_publish_results = Column(Boolean, default=False)
    
    # Relationships
    exam = relationship("Exam", back_populates="permission")

