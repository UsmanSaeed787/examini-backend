from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base
import uuid


class User(Base):
    __tablename__ = "users"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255))
    role = Column(String(20), nullable=False, index=True)
    full_name = Column(String(255))
    google_id = Column(String(255), unique=True, index=True)
    profile_image_url = Column(String)
    email_verified = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default='now()')
    updated_at = Column(DateTime(timezone=True), server_default='now()', onupdate='now()')
    
    # Relationships
    created_classes = relationship("Class", back_populates="creator", foreign_keys="Class.created_by")
    teacher_classes_rel = relationship("TeacherClass", back_populates="teacher", cascade="all, delete-orphan")
    student_classes_rel = relationship("StudentClass", back_populates="student", cascade="all, delete-orphan")
    student_profile = relationship("StudentProfile", back_populates="user", uselist=False, cascade="all, delete-orphan")
    materials = relationship("Material", back_populates="teacher", cascade="all, delete-orphan")
    exams = relationship("Exam", back_populates="teacher", cascade="all, delete-orphan")
    exam_attempts = relationship("ExamAttempt", back_populates="student", cascade="all, delete-orphan")
    sessions = relationship("Session", back_populates="user", cascade="all, delete-orphan")
    password_resets = relationship("PasswordReset", back_populates="user", cascade="all, delete-orphan")

