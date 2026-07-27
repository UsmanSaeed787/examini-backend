from sqlalchemy import Column, String, Integer, BigInteger, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base
import uuid


class Material(Base):
    __tablename__ = "materials"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    teacher_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    class_id = Column(UUID(as_uuid=True), ForeignKey("classes.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    description = Column(String)
    file_url = Column(String, nullable=False)
    file_name = Column(String(255), nullable=False)
    file_type = Column(String(50))
    file_size = Column(BigInteger)
    uploaded_at = Column(DateTime(timezone=True), server_default='now()', index=True)
    updated_at = Column(DateTime(timezone=True), server_default='now()', onupdate='now()')
    is_active = Column(Boolean, default=True)
    
    # Relationships
    teacher = relationship("User", back_populates="materials")
    class_ = relationship("Class", back_populates="materials")

