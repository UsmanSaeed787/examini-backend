from typing import List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.notification import Notification


class NotificationService:
    """Service for user notifications."""

    @staticmethod
    def create(
        db: Session,
        user_id: UUID,
        title: str,
        message: str,
        type_: str = "general",
        related_entity_type: Optional[str] = None,
        related_entity_id: Optional[UUID] = None,
    ) -> Notification:
        notification = Notification(
            user_id=user_id,
            title=title,
            message=message,
            type=type_,
            related_entity_type=related_entity_type,
            related_entity_id=related_entity_id,
        )
        db.add(notification)
        db.commit()
        db.refresh(notification)
        return notification

    @staticmethod
    def list_for_user(
        db: Session,
        user_id: UUID,
        unread_only: bool = False,
        limit: int = 50,
    ) -> List[Notification]:
        query = db.query(Notification).filter(Notification.user_id == user_id)
        if unread_only:
            query = query.filter(Notification.is_read == False)  # noqa: E712
        return query.order_by(Notification.created_at.desc()).limit(limit).all()
