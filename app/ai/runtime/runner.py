"""Agent-run orchestration on top of the kernel.

The single choke point every agent run passes through (API, facade, and
workflow AgentStageHandlers alike). Composition:

    registry -> quota policy -> run record -> lifecycle(execute_agent)
             -> usage/tracing -> cost tracker -> events/metrics -> RunOutcome

Public API is stable: execute_run(...) and ensure_enabled() keep their
signatures; cancel_run() is additive."""
import asyncio
from typing import Any, Optional
from uuid import UUID

from app.ai.config import ai_settings
from app.ai.context import AIRunContext
from app.ai.persistence import store
from app.ai.runtime import execution, provider, tracing
from app.ai.runtime.context import ExecutionContext
from app.ai.runtime.events import EventTypes, RuntimeEvent, event_bus
from app.ai.runtime.exceptions import AIDisabledError, map_sdk_exception
from app.ai.runtime.lifecycle import RetryPolicy, run_registry, run_with_lifecycle
from app.ai.runtime.quotas import default_cost_tracker, default_quota_policy
from app.ai.runtime.sessions import DBSession
from app.ai.schemas.runs import RunOutcome


def ensure_enabled() -> None:
    if not ai_settings.enabled:
        raise AIDisabledError("The AI layer is disabled (set AI_ENABLED=true to enable)")


def cancel_run(run_id: UUID) -> bool:
    """Signal cancellation of an in-flight run in this process. Returns False
    when the run is not currently executing here."""
    return run_registry.cancel(run_id)


async def execute_run(
    context: AIRunContext,
    agent_key: str,
    user_input: Any,
    session_id: Optional[str] = None,
    run_id: Optional[UUID] = None,
    version: Optional[str] = None,
) -> RunOutcome:
    """Execute one agent run to completion. Raises AIError subclasses on
    failure (mapped, never raw SDK/provider errors). `version` pins an exact
    registered agent version; None resolves the latest."""
    from app.ai.agents.registry import ensure_agent_allowed

    ensure_enabled()
    spec = ensure_agent_allowed(agent_key, context.role, version=version)
    context.agent_key = agent_key

    await default_quota_policy.check(context)

    input_summary = user_input if isinstance(user_input, str) else None
    if run_id is None:
        run_id = await asyncio.to_thread(
            store.create_run, context.user_id, agent_key, input_summary, session_id, "queued"
        )
    context.run_id = run_id
    await asyncio.to_thread(store.mark_running, run_id)

    exec_context = ExecutionContext(identity=context, run_id=run_id)
    run_registry.register(run_id, exec_context.cancel_token)
    session = DBSession(session_id) if (spec.uses_session and session_id) else None

    # Context Engine (Phase 4): assemble the immutable execution snapshot the
    # agent's tools/guardrails consume. The engine is failure-safe internally;
    # this guard exists so context assembly can never block a run.
    if ai_settings.context_engine_enabled:
        try:
            from app.ai.context_engine import build_for_identity

            context.snapshot = await build_for_identity(
                context, agent_key=agent_key, session_id=session_id
            )
        except Exception:  # noqa: BLE001
            context.snapshot = None

    await event_bus.publish(
        RuntimeEvent(
            type=EventTypes.RUN_STARTED,
            trace_id=exec_context.trace_id,
            run_id=run_id,
            user_id=context.user_id,
            payload={"agent_key": agent_key},
        )
    )

    try:
        retry = RetryPolicy(
            max_attempts=1 + max(ai_settings.max_retries, 0),
            backoff_seconds=ai_settings.retry_backoff_seconds,
            retry_on=execution.transient_exceptions(),
        )
        result = await run_with_lifecycle(
            lambda: execution.execute_agent(exec_context, spec, user_input, session),
            timeout_seconds=ai_settings.run_timeout_seconds,
            retry=retry,
            token=exec_context.cancel_token,
        )
    except Exception as exc:  # noqa: BLE001 — mapped to stable AIError codes
        error = map_sdk_exception(exc)
        await asyncio.to_thread(store.fail_run, run_id, error.code, error.message)
        await event_bus.publish(
            RuntimeEvent(
                type=EventTypes.RUN_CANCELLED if error.code == "AI_RUN_CANCELLED" else EventTypes.RUN_FAILED,
                trace_id=exec_context.trace_id,
                run_id=run_id,
                user_id=context.user_id,
                payload={"agent_key": agent_key, "error_code": error.code},
            )
        )
        raise error from exc
    finally:
        run_registry.unregister(run_id)

    usage = tracing.extract_usage(result)
    model_name = provider.resolve_model_name()
    await asyncio.to_thread(
        store.complete_run, run_id, tracing.summarize_output(result.final_output), usage, model_name
    )
    await default_cost_tracker.record(context, usage, model_name)
    await event_bus.publish(
        RuntimeEvent(
            type=EventTypes.RUN_COMPLETED,
            trace_id=exec_context.trace_id,
            run_id=run_id,
            user_id=context.user_id,
            payload={"agent_key": agent_key, **usage},
        )
    )
    return RunOutcome(
        run_id=run_id,
        agent_key=agent_key,
        status="completed",
        final_output=result.final_output,
        usage=usage,
        session_id=session_id,
    )
