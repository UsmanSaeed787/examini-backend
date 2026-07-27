"""Per-user daily quotas, checked pre-flight by the runner and fed by the
usage rows tracing writes after each run. Closes the audit's "unbounded LLM
spend" finding for everything the AI layer owns."""
from uuid import UUID

from app.ai.config import ai_settings
from app.ai.persistence import store
from app.ai.runtime.errors import AIQuotaExceededError


def check_user_quota(user_id: UUID) -> None:
    """Synchronous (called via asyncio.to_thread). Raises on exhaustion."""
    runs = store.runs_today(user_id)
    if runs >= ai_settings.max_runs_per_day:
        raise AIQuotaExceededError(
            "Daily AI run limit reached",
            details={"limit": ai_settings.max_runs_per_day, "used": runs},
        )
    tokens = store.tokens_today(user_id)
    if tokens >= ai_settings.max_tokens_per_day:
        raise AIQuotaExceededError(
            "Daily AI token budget exhausted",
            details={"limit": ai_settings.max_tokens_per_day, "used": tokens},
        )
