from sqlalchemy import Column, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base
import uuid


class Class(Base):
    __tablename__ = "classes"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False, index=True)
    description = Column(String)
    created_at = Column(DateTime(timezone=True), server_default='now()')
    updated_at = Column(DateTime(timezone=True), server_default='now()', onupdate='now()')
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    
    # Relationships
    creator = relationship("User", foreign_keys=[created_by], back_populates="created_classes")
    sections = relationship("Section", back_populates="class_", cascade="all, delete-orphan")
    teacher_classes = relationship("TeacherClass", back_populates="class_", cascade="all, delete-orphan")
    student_classes = relationship("StudentClass", back_populates="class_", cascade="all, delete-orphan")
    materials = relationship("Material", back_populates="class_", cascade="all, delete-orphan")
    exams = relationship("Exam", back_populates="class_", cascade="all, delete-orphan")


class Section(Base):
    __tablename__ = "sections"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    class_id = Column(UUID(as_uuid=True), ForeignKey("classes.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(String)
    created_at = Column(DateTime(timezone=True), server_default='now()')
    updated_at = Column(DateTime(timezone=True), server_default='now()', onupdate='now()')
    
    # Relationships
    class_ = relationship("Class", back_populates="sections")
    student_classes = relationship("StudentClass", back_populates="section", cascade="all, delete-orphan")
    exam_sections = relationship("ExamSection", back_populates="section", cascade="all, delete-orphan")


class TeacherClass(Base):
    __tablename__ = "teacher_classes"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    teacher_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    class_id = Column(UUID(as_uuid=True), ForeignKey("classes.id", ondelete="CASCADE"), nullable=False, index=True)
    assigned_at = Column(DateTime(timezone=True), server_default='now()')
    
    # Relationships
    teacher = relationship("User", back_populates="teacher_classes_rel")
    class_ = relationship("Class", back_populates="teacher_classes")


class StudentClass(Base):
    __tablename__ = "student_classes"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    student_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    class_id = Column(UUID(as_uuid=True), ForeignKey("classes.id", ondelete="CASCADE"), nullable=False, index=True)
    section_id = Column(UUID(as_uuid=True), ForeignKey("sections.id", ondelete="CASCADE"), nullable=False, index=True)
    roll_number = Column(String(50), index=True)
    enrolled_at = Column(DateTime(timezone=True), server_default='now()')
    
    # Relationships
    student = relationship("User", back_populates="student_classes_rel")
    class_ = relationship("Class", back_populates="student_classes")
    section = relationship("Section", back_populates="student_classes")

