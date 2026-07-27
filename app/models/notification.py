from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base
import uuid


class Notification(Base):
    __tablename__ = "notifications"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    message = Column(String, nullable=False)
    type = Column(String(50), nullable=False)
    related_entity_type = Column(String(50))
    related_entity_id = Column(UUID(as_uuid=True))
    is_read = Column(Boolean, default=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default='now()', index=True)
    
    # Relationships
    user = relationship("User")


class AuditLog(Base):
    __tablename__ = "audit_logs"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True)
    action = Column(String(100), nullable=False, index=True)
    entity_type = Column(String(50))
    entity_id = Column(UUID(as_uuid=True))
    details = Column(String)  # JSON stored as string, can be parsed
    ip_address = Column(String(45))
    user_agent = Column(String)
    created_at = Column(DateTime(timezone=True), server_default='now()', index=True)
    
    # Relationships
    user = relationship("User")

