"""Kernel contracts (dependency-inversion surface).

Everything the runtime orchestrates is expressed as a Protocol here, so any
capability (Assessment Intelligence, Student Success, Teacher Copilot,
Administrator Intelligence, Academic Analytics, Career Intelligence) plugs in
by implementing an interface — the kernel never imports capability code.
"""
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional, Protocol, runtime_checkable

from app.ai.context import AIRunContext


@runtime_checkable
class EventSink(Protocol):
    """Receives runtime events (events.py publishes to all registered sinks)."""

    async def publish(self, event: Any) -> None: ...


@runtime_checkable
class MetricsSink(Protocol):
    """Receives counters and observations (metrics.py)."""

    def increment(self, name: str, value: float = 1.0, **labels: str) -> None: ...
    def observe(self, name: str, value: float, **labels: str) -> None: ...


@runtime_checkable
class QuotaPolicy(Protocol):
    """Pre-flight admission control for a unit of execution."""

    async def check(self, identity: AIRunContext) -> None: ...


@runtime_checkable
class CostTracker(Protocol):
    """Post-run cost/usage hook (pricing models plug in here)."""

    async def record(self, identity: AIRunContext, usage: dict, model: Optional[str]) -> None: ...


@runtime_checkable
class ExecutableStage(Protocol):
    """One executable pipeline stage (workflow handlers and future
    agent-backed handlers both satisfy this)."""

    key: Any

    async def execute(self, ctx: Any) -> Any: ...


@dataclass
class StagePlan:
    """What the pipeline executor needs to run one stage: the handler, its
    context, whether to pause afterward for human approval, and an optional
    artifact validator. Produced by PipelineHooks.begin_stage()."""

    stage_key: str
    handler: ExecutableStage
    context: Any
    pause_after: bool = False
    validate: Optional[Callable[[Any], None]] = None  # raises on bad artifact


@runtime_checkable
class PipelineHooks(Protocol):
    """The persistence/policy half of a pipeline, owned by the capability.

    The kernel drives the loop; the hooks own state (DB rows, transitions,
    checkpoint policy). begin_stage() returning None ends the loop (nothing
    runnable: paused, terminal, or done)."""

    async def begin_stage(self) -> Optional[StagePlan]: ...
    async def complete_stage(self, plan: StagePlan, artifact: Any, paused: bool) -> None: ...
    async def fail_stage(self, plan: StagePlan, message: str) -> None: ...


# Factory type used by lifecycle.run_with_lifecycle: builds a fresh awaitable
# per attempt (a coroutine object cannot be awaited twice).
AttemptFactory = Callable[[], Awaitable[Any]]
