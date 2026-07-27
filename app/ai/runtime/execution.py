"""Execution engines.

Two generic engines, no business/workflow/agent specifics:

- execute_agent(): runs ONE registered SDK agent under the platform model.
  The only module (besides provider.py) that touches the OpenAI Agents SDK,
  imported lazily.
- PipelineExecutor: drives ANY stage pipeline through PipelineHooks. The
  kernel owns the loop, instrumentation, and pause semantics; the capability
  (via hooks) owns state, transitions, and checkpoint policy. This is what
  Assessment Intelligence runs on today and what Student Success, Teacher
  Copilot, Administrator Intelligence, Academic Analytics, and Career
  Intelligence plug into tomorrow.
"""
from typing import Any, Optional, Tuple, Type

from app.ai.config import ai_settings
from app.ai.runtime import provider
from app.ai.runtime.context import ExecutionContext
from app.ai.runtime.events import EventTypes, RuntimeEvent, event_bus
from app.ai.runtime.exceptions import AIError, describe_error
from app.ai.runtime.interfaces import PipelineHooks
from app.ai.runtime.results import ExecutionError, PipelineResult, PipelineStatus
from app.ai.runtime.tracing import span


async def execute_agent(
    context: ExecutionContext,
    spec,
    user_input: Any,
    session=None,
):
    """Run one SDK agent to completion and return the raw RunResult.
    Lifecycle (timeout/retry/cancel) is applied by the caller via
    lifecycle.run_with_lifecycle — this function does exactly one attempt.

    `spec` is an AgentDefinition-shaped object (factory + optional
    model_overrides); per-agent model configuration is honored here, with
    AISettings as the fallback for anything not overridden."""
    from agents import ModelSettings, RunConfig, Runner

    overrides = getattr(spec, "model_overrides", None)
    max_turns = (overrides.max_turns if overrides and overrides.max_turns else ai_settings.max_turns)
    settings_kwargs: dict = {
        "max_tokens": (
            overrides.max_output_tokens
            if overrides and overrides.max_output_tokens
            else ai_settings.max_output_tokens
        )
    }
    if overrides and overrides.temperature is not None:
        settings_kwargs["temperature"] = overrides.temperature

    agent = spec.factory()
    return await Runner.run(
        agent,
        user_input,
        context=context.identity,
        max_turns=max_turns,
        run_config=RunConfig(
            model=provider.build_model(overrides.model if overrides else None),
            model_settings=ModelSettings(**settings_kwargs),
            workflow_name=f"examini:{getattr(spec, 'key', None) or context.identity.agent_key or 'agent'}",
            tracing_disabled=not ai_settings.tracing_enabled,
        ),
        session=session,
    )


def transient_exceptions() -> Tuple[Type[BaseException], ...]:
    """Exception types worth retrying (provider hiccups, malformed model
    output) — never guardrail rejections, cancellations, or timeouts."""
    types: list[Type[BaseException]] = []
    try:
        from agents.exceptions import ModelBehaviorError

        types.append(ModelBehaviorError)
    except ImportError:
        pass
    try:
        from openai import APIConnectionError, APITimeoutError, InternalServerError, RateLimitError

        types.extend([APIConnectionError, APITimeoutError, InternalServerError, RateLimitError])
    except ImportError:
        pass
    return tuple(types)


class PipelineExecutor:
    """Generic pause-aware pipeline loop over PipelineHooks.

    Loop: begin_stage() -> StagePlan | None
          run plan.handler.execute(plan.context) inside a span
          plan.validate(artifact) if provided
          complete_stage(plan, artifact, paused=plan.pause_after)
          pause_after -> return PAUSED; else continue until None -> COMPLETED
    Exceptions in `catch` are routed to fail_stage() and end the pipeline as
    FAILED; anything else propagates (a kernel bug, not a stage failure)."""

    def __init__(self, catch: Tuple[Type[BaseException], ...] = (AIError,)):
        self._catch = catch

    async def run(
        self, hooks: PipelineHooks, *, context: Optional[ExecutionContext] = None
    ) -> PipelineResult:
        trace_id = context.trace_id if context else None
        workflow_id = context.workflow_id if context else None
        stages_run = 0

        while True:
            plan = await hooks.begin_stage()
            if plan is None:
                if stages_run == 0:
                    return PipelineResult(status=PipelineStatus.IDLE)
                await event_bus.publish(
                    RuntimeEvent(
                        type=EventTypes.PIPELINE_COMPLETED,
                        trace_id=trace_id,
                        workflow_id=workflow_id,
                        payload={"stages_run": stages_run},
                    )
                )
                return PipelineResult(status=PipelineStatus.COMPLETED, stages_run=stages_run)

            try:
                async with span(
                    "stage",
                    trace_id=trace_id,
                    workflow_id=workflow_id,
                    stage_key=plan.stage_key,
                ):
                    artifact = await plan.handler.execute(plan.context)
                    if plan.validate is not None:
                        plan.validate(artifact)
            except self._catch as exc:  # noqa: PERF203 — stage failure path
                # describe_error unpacks AIError.details, so a guardrail
                # rejection reports WHICH check failed rather than just that
                # one did.
                message = describe_error(exc)
                await hooks.fail_stage(plan, message)
                return PipelineResult(
                    status=PipelineStatus.FAILED,
                    stage_key=plan.stage_key,
                    error=ExecutionError(code=exc.__class__.__name__, message=message),
                    stages_run=stages_run,
                )

            stages_run += 1
            await hooks.complete_stage(plan, artifact, plan.pause_after)
            if plan.pause_after:
                await event_bus.publish(
                    RuntimeEvent(
                        type=EventTypes.PIPELINE_PAUSED,
                        trace_id=trace_id,
                        workflow_id=workflow_id,
                        stage_key=plan.stage_key,
                    )
                )
                return PipelineResult(
                    status=PipelineStatus.PAUSED,
                    stage_key=plan.stage_key,
                    stages_run=stages_run,
                )
