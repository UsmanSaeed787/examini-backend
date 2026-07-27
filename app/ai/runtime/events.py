"""Runtime event publishing.

An in-process, async event bus with pluggable sinks (interfaces.EventSink).
Default sink logs under the 'app.ai.runtime' logger. Future sinks (DB audit
writer, webhook, SSE feed) subscribe without touching publishers. A failing
sink never breaks execution."""
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from app.ai.runtime.interfaces import EventSink

logger = logging.getLogger("app.ai.runtime")


class EventTypes:
    RUN_STARTED = "run.started"
    RUN_COMPLETED = "run.completed"
    RUN_FAILED = "run.failed"
    RUN_CANCELLED = "run.cancelled"
    STAGE_STARTED = "stage.started"
    STAGE_COMPLETED = "stage.completed"
    STAGE_FAILED = "stage.failed"
    PIPELINE_PAUSED = "pipeline.paused"       # human approval checkpoint reached
    PIPELINE_COMPLETED = "pipeline.completed"
    COST_RECORDED = "cost.recorded"


@dataclass
class RuntimeEvent:
    type: str
    at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    trace_id: Optional[str] = None
    run_id: Optional[UUID] = None
    workflow_id: Optional[UUID] = None
    stage_key: Optional[str] = None
    user_id: Optional[UUID] = None
    payload: Dict[str, Any] = field(default_factory=dict)


class LoggingEventSink:
    async def publish(self, event: RuntimeEvent) -> None:
        logger.info(
            "ai.event %s trace=%s run=%s workflow=%s stage=%s",
            event.type,
            event.trace_id,
            event.run_id,
            event.workflow_id,
            event.stage_key,
        )


class EventBus:
    def __init__(self) -> None:
        self._sinks: List[EventSink] = []

    def subscribe(self, sink: EventSink) -> None:
        if sink not in self._sinks:
            self._sinks.append(sink)

    def unsubscribe(self, sink: EventSink) -> None:
        if sink in self._sinks:
            self._sinks.remove(sink)

    async def publish(self, event: RuntimeEvent) -> None:
        for sink in list(self._sinks):
            try:
                await sink.publish(event)
            except Exception:  # noqa: BLE001 — observability must never break execution
                logger.exception("event sink %r failed for %s", sink, event.type)


event_bus = EventBus()
event_bus.subscribe(LoggingEventSink())
