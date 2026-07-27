"""AI-surface dependencies. Reuses the platform's existing auth deps —
identity and role resolution are identical to every other router."""
from fastapi import Depends

from app.ai.config import ai_settings
from app.ai.context import AIRunContext
from app.ai.runtime.errors import AIDisabledError
from app.api.deps import get_current_active_user
from app.models.user import User


def require_ai_enabled() -> None:
    if not ai_settings.enabled:
        raise AIDisabledError("The AI layer is disabled")


def build_context(current_user: User = Depends(get_current_active_user)) -> AIRunContext:
    return AIRunContext(
        user_id=current_user.id,
        role=current_user.role,
        full_name=current_user.full_name,
    )


def admin_context(
    context: AIRunContext = Depends(build_context),
    _: None = Depends(require_ai_enabled),
) -> AIRunContext:
    from app.middleware.error_handler import AuthorizationError
    from app.utils.constants import UserRole

    if context.role != UserRole.ADMIN.value:
        raise AuthorizationError("Admin access required")
    return context
