"""Runtime quota + cost-tracking policies (interfaces.QuotaPolicy /
CostTracker implementations).

The default quota delegates to policies/quotas.py — the runtime owns the
protocol and injection point, the policy layer owns the numbers. Cost
tracking is a hook: v1 publishes a cost.recorded event carrying usage; a
pricing model can subscribe to it (or replace the tracker) without touching
the runner."""
import asyncio
from typing import Optional

from app.ai.context import AIRunContext
from app.ai.runtime.events import EventTypes, RuntimeEvent, event_bus


class DailyUserQuotaPolicy:
    async def check(self, identity: AIRunContext) -> None:
        from app.ai.policies.quotas import check_user_quota

        await asyncio.to_thread(check_user_quota, identity.user_id)


class NullQuotaPolicy:
    async def check(self, identity: AIRunContext) -> None:
        return None


class EventCostTracker:
    """Publishes usage as a cost.recorded event (token counts persist to
    ai_usage via the run store; monetary pricing subscribes here later)."""

    async def record(self, identity: AIRunContext, usage: dict, model: Optional[str]) -> None:
        await event_bus.publish(
            RuntimeEvent(
                type=EventTypes.COST_RECORDED,
                run_id=identity.run_id,
                user_id=identity.user_id,
                payload={"model": model, **usage},
            )
        )


class NullCostTracker:
    async def record(self, identity: AIRunContext, usage: dict, model: Optional[str]) -> None:
        return None


default_quota_policy = DailyUserQuotaPolicy()
default_cost_tracker = EventCostTracker()
