"""Notification tools — wrap NotificationService."""
from uuid import UUID

from pydantic import BaseModel, Field

from app.ai.tools.registry import ToolContext, tool
from app.services.notification_service import NotificationService


class SendNotificationParams(BaseModel):
    user_id: str = Field(description="Recipient user id (UUID)")
    title: str = Field(min_length=1, max_length=255)
    message: str = Field(min_length=1)


@tool(
    key="notifications.send",
    description="Send an in-app notification to a user (teacher/admin roles only).",
    params=SendNotificationParams,
    services=("NotificationService",),
    tags=("notifications", "write"),
)
def send_notification(ctx: ToolContext, params: SendNotificationParams) -> dict:
    with ctx.db() as db:
        notification = NotificationService.create(
            db,
            user_id=UUID(params.user_id),
            title=params.title[:255],
            message=params.message,
            type_="ai",
            related_entity_type="ai_run",
            related_entity_id=ctx.identity.run_id,
        )
        return {"id": str(notification.id), "sent": True}
