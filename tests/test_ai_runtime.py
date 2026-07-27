"""Unit tests for the AI Runtime kernel (lifecycle, events, metrics,
registry, results, pipeline executor) — all pure async, no DB, no SDK calls."""
import asyncio

import pytest

from app.ai.runtime.events import EventBus, RuntimeEvent
from app.ai.runtime.exceptions import (
    AIRunTimeoutError,
    ExecutionCancelledError,
    RegistryError,
    RetryExhaustedError,
)
from app.ai.runtime.execution import PipelineExecutor
from app.ai.runtime.interfaces import StagePlan
from app.ai.runtime.lifecycle import (
    CancellationRegistry,
    CancellationToken,
    RetryPolicy,
    run_with_lifecycle,
)
from app.ai.runtime.metrics import InMemoryMetricsSink
from app.ai.runtime.registry import Registry
from app.ai.runtime.results import PipelineStatus
from app.middleware.error_handler import NotFoundError, ValidationError


# ---------------------------------------------------------------- lifecycle

class TestLifecycle:
    async def test_success_passthrough(self):
        async def work():
            return 42

        assert await run_with_lifecycle(work) == 42

    async def test_timeout_raises(self):
        async def slow():
            await asyncio.sleep(5)

        with pytest.raises(AIRunTimeoutError):
            await run_with_lifecycle(slow, timeout_seconds=0.05)

    async def test_cancellation_pre_flight(self):
        token = CancellationToken()
        token.cancel()

        async def work():
            return 1

        with pytest.raises(ExecutionCancelledError):
            await run_with_lifecycle(work, token=token)

    async def test_cancellation_mid_flight(self):
        token = CancellationToken()

        async def slow():
            await asyncio.sleep(5)

        async def cancel_soon():
            await asyncio.sleep(0.05)
            token.cancel()

        cancel_task = asyncio.create_task(cancel_soon())
        with pytest.raises(ExecutionCancelledError):
            await run_with_lifecycle(slow, token=token)
        await cancel_task

    async def test_retry_then_success(self):
        attempts = {"n": 0}

        async def flaky():
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise ConnectionError("transient")
            return "ok"

        result = await run_with_lifecycle(
            flaky, retry=RetryPolicy(max_attempts=3, retry_on=(ConnectionError,))
        )
        assert result == "ok"
        assert attempts["n"] == 3

    async def test_retry_exhausted(self):
        async def always_fails():
            raise ConnectionError("transient")

        with pytest.raises(RetryExhaustedError):
            await run_with_lifecycle(
                always_fails, retry=RetryPolicy(max_attempts=2, retry_on=(ConnectionError,))
            )

    async def test_non_retryable_propagates_immediately(self):
        attempts = {"n": 0}

        async def fails():
            attempts["n"] += 1
            raise ValueError("permanent")

        with pytest.raises(ValueError):
            await run_with_lifecycle(
                fails, retry=RetryPolicy(max_attempts=3, retry_on=(ConnectionError,))
            )
        assert attempts["n"] == 1

    def test_cancellation_registry(self):
        registry = CancellationRegistry()
        token = CancellationToken()
        from uuid import uuid4

        run_id = uuid4()
        registry.register(run_id, token)
        assert registry.cancel(run_id) is True
        assert token.cancelled
        registry.unregister(run_id)
        assert registry.cancel(run_id) is False


# ---------------------------------------------------------------- events/metrics

class _CollectingSink:
    def __init__(self):
        self.events = []

    async def publish(self, event):
        self.events.append(event)


class _ExplodingSink:
    async def publish(self, event):
        raise RuntimeError("sink down")


class TestEventsAndMetrics:
    async def test_bus_delivers_to_all_sinks(self):
        bus = EventBus()
        a, b = _CollectingSink(), _CollectingSink()
        bus.subscribe(a)
        bus.subscribe(b)
        await bus.publish(RuntimeEvent(type="x"))
        assert len(a.events) == 1 and len(b.events) == 1

    async def test_failing_sink_never_breaks_publishing(self):
        bus = EventBus()
        collector = _CollectingSink()
        bus.subscribe(_ExplodingSink())
        bus.subscribe(collector)
        await bus.publish(RuntimeEvent(type="x"))
        assert len(collector.events) == 1

    def test_metrics_counters_and_observations(self):
        sink = InMemoryMetricsSink()
        sink.increment("runs", 1, agent="grader")
        sink.increment("runs", 2, agent="grader")
        sink.observe("latency", 10.0)
        sink.observe("latency", 20.0)
        snap = sink.snapshot()
        assert list(snap["counters"].values()) == [3]
        assert snap["observations"]["latency"]["avg"] == 15.0


# ---------------------------------------------------------------- registry

class TestRegistry:
    def test_register_get_and_duplicate_protection(self):
        reg: Registry[str] = Registry("thing")
        reg.register("a", "A")
        assert reg.get("a") == "A"
        with pytest.raises(RegistryError):
            reg.register("a", "B")
        reg.register("a", "B", override=True)
        assert reg.get("a") == "B"

    def test_unknown_key_raises_not_found(self):
        reg: Registry[str] = Registry("thing")
        with pytest.raises(NotFoundError):
            reg.get("missing")

    def test_assessment_workflow_is_catalogued(self):
        import app.ai.workflows.assessment.service  # noqa: F401 — registration side effect
        from app.ai.runtime.registry import workflow_registry

        definition = workflow_registry.get("assessment")
        assert definition.title == "Assessment Intelligence"
        assert "curriculum_analysis" in definition.stage_keys


# ---------------------------------------------------------------- pipeline executor

class _StubHandler:
    def __init__(self, key, fail=False):
        self.key = key
        self._fail = fail

    async def execute(self, ctx):
        if self._fail:
            raise ValidationError(f"{self.key} exploded")
        return {"stage": self.key}


class _ScriptedHooks:
    """Feeds a scripted sequence of StagePlans and records callbacks."""

    def __init__(self, plans):
        self._plans = list(plans)
        self.completed = []
        self.failed = []

    async def begin_stage(self):
        return self._plans.pop(0) if self._plans else None

    async def complete_stage(self, plan, artifact, paused):
        self.completed.append((plan.stage_key, paused))

    async def fail_stage(self, plan, message):
        self.failed.append((plan.stage_key, message))


class TestPipelineExecutor:
    async def test_runs_to_completion(self):
        hooks = _ScriptedHooks(
            [
                StagePlan(stage_key="one", handler=_StubHandler("one"), context=None),
                StagePlan(stage_key="two", handler=_StubHandler("two"), context=None),
            ]
        )
        result = await PipelineExecutor(catch=(ValidationError,)).run(hooks)
        assert result.status == PipelineStatus.COMPLETED
        assert result.stages_run == 2
        assert hooks.completed == [("one", False), ("two", False)]

    async def test_pauses_at_checkpoint(self):
        hooks = _ScriptedHooks(
            [StagePlan(stage_key="one", handler=_StubHandler("one"), context=None, pause_after=True)]
        )
        result = await PipelineExecutor(catch=(ValidationError,)).run(hooks)
        assert result.status == PipelineStatus.PAUSED
        assert result.stage_key == "one"
        assert hooks.completed == [("one", True)]

    async def test_stage_failure_routes_to_fail_hook(self):
        hooks = _ScriptedHooks(
            [StagePlan(stage_key="bad", handler=_StubHandler("bad", fail=True), context=None)]
        )
        result = await PipelineExecutor(catch=(ValidationError,)).run(hooks)
        assert result.status == PipelineStatus.FAILED
        assert hooks.failed and hooks.failed[0][0] == "bad"

    async def test_validator_failure_fails_stage(self):
        def reject(artifact):
            raise ValidationError("wrong artifact shape")

        hooks = _ScriptedHooks(
            [StagePlan(stage_key="one", handler=_StubHandler("one"), context=None, validate=reject)]
        )
        result = await PipelineExecutor(catch=(ValidationError,)).run(hooks)
        assert result.status == PipelineStatus.FAILED

    async def test_idle_when_nothing_runnable(self):
        result = await PipelineExecutor().run(_ScriptedHooks([]))
        assert result.status == PipelineStatus.IDLE
