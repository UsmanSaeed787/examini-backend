"""Tracing: correlation spans + usage extraction.

span() wraps any unit of execution, emitting started/completed/failed events
on the bus and a duration observation to metrics — the one instrumentation
primitive the runner and pipeline executor share. Usage extraction stays here
as the cost-tracking source of truth."""
from contextlib import asynccontextmanager
from time import perf_counter
from typing import Optional
from uuid import UUID

from app.ai.runtime.events import RuntimeEvent, event_bus
from app.ai.runtime.metrics import metrics


@asynccontextmanager
async def span(
    name: str,
    *,
    trace_id: Optional[str] = None,
    run_id: Optional[UUID] = None,
    workflow_id: Optional[UUID] = None,
    stage_key: Optional[str] = None,
    user_id: Optional[UUID] = None,
    payload: Optional[dict] = None,
):
    common = dict(
        trace_id=trace_id,
        run_id=run_id,
        workflow_id=workflow_id,
        stage_key=stage_key,
        user_id=user_id,
    )
    start = perf_counter()
    await event_bus.publish(RuntimeEvent(type=f"{name}.started", payload=payload or {}, **common))
    try:
        yield
    except Exception as exc:
        duration_ms = (perf_counter() - start) * 1000
        metrics.observe(f"{name}.duration_ms", duration_ms, outcome="failed")
        metrics.increment(f"{name}.failed")
        await event_bus.publish(
            RuntimeEvent(
                type=f"{name}.failed",
                payload={"error": exc.__class__.__name__, "duration_ms": duration_ms},
                **common,
            )
        )
        raise
    duration_ms = (perf_counter() - start) * 1000
    metrics.observe(f"{name}.duration_ms", duration_ms, outcome="completed")
    metrics.increment(f"{name}.completed")
    await event_bus.publish(
        RuntimeEvent(type=f"{name}.completed", payload={"duration_ms": duration_ms}, **common)
    )


def extract_usage(result) -> dict:
    """Pull token usage off an SDK RunResult; tolerant of shape drift."""
    usage = getattr(getattr(result, "context_wrapper", None), "usage", None)
    if usage is None:
        return {"requests": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    return {
        "requests": int(getattr(usage, "requests", 0) or 0),
        "input_tokens": int(getattr(usage, "input_tokens", 0) or 0),
        "output_tokens": int(getattr(usage, "output_tokens", 0) or 0),
        "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
    }


def summarize_output(final_output, max_chars: int = 2000) -> Optional[str]:
    """Short, storable representation of a run's final output."""
    if final_output is None:
        return None
    try:
        from pydantic import BaseModel

        if isinstance(final_output, BaseModel):
            text = final_output.model_dump_json()
        else:
            text = str(final_output)
    except Exception:
        text = str(final_output)
    return text[:max_chars]
