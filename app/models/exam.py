from sqlalchemy import Column, String, Integer, Boolean, DateTime, ForeignKey, Numeric
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from app.database import Base
import uuid


class Exam(Base):
    __tablename__ = "exams"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    teacher_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    class_id = Column(UUID(as_uuid=True), ForeignKey("classes.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    description = Column(String)
    duration_minutes = Column(Integer, nullable=False)
    start_date = Column(DateTime(timezone=True), index=True)
    end_date = Column(DateTime(timezone=True), index=True)
    is_published = Column(Boolean, default=False, index=True)
    allow_retake = Column(Boolean, default=False)
    max_attempts = Column(Integer, default=1)
    created_at = Column(DateTime(timezone=True), server_default='now()')
    updated_at = Column(DateTime(timezone=True), server_default='now()', onupdate='now()')
    
    # Relationships
    teacher = relationship("User", back_populates="exams")
    class_ = relationship("Class", back_populates="exams")
    exam_sections = relationship("ExamSection", back_populates="exam", cascade="all, delete-orphan")
    questions = relationship("Question", back_populates="exam", cascade="all, delete-orphan", order_by="Question.order_number")
    attempts = relationship("ExamAttempt", back_populates="exam", cascade="all, delete-orphan")
    permission = relationship("ExamPermission", back_populates="exam", uselist=False, cascade="all, delete-orphan")


class ExamSection(Base):
    __tablename__ = "exam_sections"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    exam_id = Column(UUID(as_uuid=True), ForeignKey("exams.id", ondelete="CASCADE"), nullable=False, index=True)
    section_id = Column(UUID(as_uuid=True), ForeignKey("sections.id", ondelete="CASCADE"), nullable=False, index=True)
    assigned_at = Column(DateTime(timezone=True), server_default='now()')
    
    # Relationships
    exam = relationship("Exam", back_populates="exam_sections")
    section = relationship("Section", back_populates="exam_sections")


class Question(Base):
    __tablename__ = "questions"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    exam_id = Column(UUID(as_uuid=True), ForeignKey("exams.id", ondelete="CASCADE"), nullable=False, index=True)
    question_text = Column(String, nullable=False)
    question_type = Column(String(20), nullable=False, index=True)
    difficulty_level = Column(String(10), index=True)
    points = Column(Numeric(5, 2), default=1.0)
    order_number = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default='now()')
    
    # Relationships
    exam = relationship("Exam", back_populates="questions")
    options = relationship("QuestionOption", back_populates="question", cascade="all, delete-orphan", order_by="QuestionOption.order_number")
    responses = relationship("ExamResponse", back_populates="question", cascade="all, delete-orphan")


class QuestionOption(Base):
    __tablename__ = "question_options"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    question_id = Column(UUID(as_uuid=True), ForeignKey("questions.id", ondelete="CASCADE"), nullable=False, index=True)
    option_text = Column(String, nullable=False)
    is_correct = Column(Boolean, default=False)
    order_number = Column(Integer, nullable=False)
    
    # Relationships
    question = relationship("Question", back_populates="options")


class QuestionBank(Base):
    __tablename__ = "question_bank"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    teacher_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    question_text = Column(String, nullable=False)
    question_type = Column(String(20), nullable=False, index=True)
    difficulty_level = Column(String(10), index=True)
    tags = Column(ARRAY(String))
    created_at = Column(DateTime(timezone=True), server_default='now()')
    updated_at = Column(DateTime(timezone=True), server_default='now()', onupdate='now()')
    
    # Relationships
    teacher = relationship("User")

