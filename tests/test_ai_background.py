"""Unit tests for background execution (Phase 12): detached task handling,
error description, and the staleness reclamation that recovers a run whose
worker died mid-flight."""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.ai.jobs.tasks import active_count, spawn
from app.ai.runtime.exceptions import AIGuardrailRejectedError, describe_error
from app.ai.workflows.assessment.domain import GenerationStatus, StageStatus, WorkflowState
from app.services.parser_service import distinct_text_length


class TestDescribeError:
    def test_unpacks_guardrail_details(self):
        exc = AIGuardrailRejectedError(
            "The request or the AI output failed validation",
            details={"errors": ["The analysis contains no topics"]},
        )
        described = describe_error(exc)
        assert "no topics" in described
        assert described.startswith("The request or the AI output failed validation")

    def test_joins_multiple_errors(self):
        exc = AIGuardrailRejectedError("failed", details={"errors": ["a", "b"]})
        assert describe_error(exc) == "failed: a; b"

    def test_falls_back_to_message_without_details(self):
        assert describe_error(AIGuardrailRejectedError("plain")) == "plain"

    def test_handles_a_plain_exception(self):
        assert describe_error(ValueError("boom")) == "boom"


class TestProviderFailureIsLegible:
    """A provider 429 used to arrive as the catch-all "AI run failed", which
    told an operator nothing. These pin the diagnosis path."""

    def _rate_limit_error(self):
        import httpx
        from openai import RateLimitError

        request = httpx.Request("POST", "https://example.invalid/v1/chat/completions")
        response = httpx.Response(429, request=request)
        return RateLimitError(
            "Error code: 429 - quota exceeded for metric generate_content_free_tier",
            response=response,
            body=None,
        )

    def test_rate_limit_maps_to_a_429_not_a_generic_failure(self):
        from app.ai.runtime.exceptions import AIProviderRateLimitedError, map_sdk_exception

        mapped = map_sdk_exception(self._rate_limit_error())
        assert isinstance(mapped, AIProviderRateLimitedError)
        assert mapped.code == "AI_PROVIDER_RATE_LIMITED"
        assert mapped.status_code == 429

    def test_rate_limit_message_is_actionable(self):
        from app.ai.runtime.exceptions import describe_error, map_sdk_exception

        described = describe_error(map_sdk_exception(self._rate_limit_error()))
        assert "rate-limiting" in described
        assert "quota" in described.lower()

    def test_unmapped_failure_keeps_its_cause(self):
        """The catch-all must stay a stable code but must not swallow what
        actually happened."""
        from app.ai.runtime.exceptions import describe_error, map_sdk_exception

        mapped = map_sdk_exception(RuntimeError("socket exploded"))
        assert mapped.code == "AI_RUN_FAILED"
        assert "RuntimeError" in describe_error(mapped)
        assert "socket exploded" in describe_error(mapped)

    def test_retry_exhaustion_adopts_a_recognised_cause(self):
        """Retrying must not mask a 429 behind a generic 502."""
        from app.ai.runtime.lifecycle import _exhausted

        exhausted = _exhausted(self._rate_limit_error(), 3)
        assert exhausted.code == "AI_PROVIDER_RATE_LIMITED"
        assert exhausted.status_code == 429
        assert "3 attempts" in str(exhausted)

    def test_retry_exhaustion_stays_generic_for_an_unrecognised_cause(self):
        from app.ai.runtime.lifecycle import _exhausted

        exhausted = _exhausted(RuntimeError("who knows"), 2)
        assert exhausted.code == "AI_RETRY_EXHAUSTED"

    def test_retries_are_enabled_and_cover_provider_errors(self):
        """The machinery shipped switched off; a single burst 429 failed an
        entire workflow that a short wait would have completed."""
        from app.ai.config import ai_settings
        from app.ai.runtime.execution import transient_exceptions
        from openai import RateLimitError

        assert ai_settings.max_retries >= 1
        assert RateLimitError in transient_exceptions()


class TestDistinctTextLength:
    def test_repeated_watermark_collapses(self):
        """A scanner stamps its name on every page; page count must not be
        mistaken for content."""
        assert distinct_text_length("CamScanner\n\n" * 200) == len("CamScanner")

    def test_real_prose_is_unaffected(self):
        text = "The cell is the unit of life.\nMitochondria produce ATP.\nRibosomes build proteins."
        assert distinct_text_length(text) == sum(
            len(line) for line in text.splitlines() if line.strip()
        )

    def test_blank_lines_ignored(self):
        assert distinct_text_length("\n\n   \n") == 0

    def test_scanned_pdf_falls_below_the_floor_a_raw_count_would_pass(self):
        from app.services.parser_service import MIN_EXTRACTED_CHARS

        scanned = "CamScanner\n\n" * 8
        assert len(scanned.strip()) > MIN_EXTRACTED_CHARS  # the old check passed it
        assert distinct_text_length(scanned) < MIN_EXTRACTED_CHARS  # the new one does not


class TestTaskSpawn:
    async def test_runs_detached_and_keeps_a_reference(self):
        done = asyncio.Event()

        async def work() -> None:
            await asyncio.sleep(0)
            done.set()

        task = spawn(work(), label="test:ok")
        assert active_count() >= 1  # a strong reference is held while running
        await asyncio.wait_for(done.wait(), timeout=2)
        await task
        assert task.done()

    async def test_failure_does_not_propagate_to_the_caller(self):
        """A detached failure is recorded on the row and logged; it must never
        surface as an unhandled rejection in the request that spawned it."""

        async def boom() -> None:
            raise RuntimeError("detached failure")

        task = spawn(boom(), label="test:boom")
        await asyncio.sleep(0.05)
        assert task.done()
        assert isinstance(task.exception(), RuntimeError)


def _stage(status: StageStatus, age_seconds: float):
    return SimpleNamespace(
        stage_key="curriculum_analysis",
        status=status.value,
        started_at=datetime.now(timezone.utc) - timedelta(seconds=age_seconds),
    )


class _FakeQuery:
    def __init__(self, result):
        self._result = result

    def filter(self, *_args, **_kwargs):
        return self

    def first(self):
        return self._result


class _FakeDB:
    def __init__(self, result):
        self._result = result
        self.committed = False

    def query(self, *_args):
        return _FakeQuery(self._result)

    def commit(self):
        self.committed = True


class TestStageReclamation:
    """A worker that dies mid-run leaves a stage RUNNING with nothing driving
    it. Reclamation must free it, but must never cut short a slow-but-alive
    stage."""

    def _workflow(self):
        return SimpleNamespace(
            id="w", state=WorkflowState.IN_PROGRESS.value, error=None,
            finished_at=None, updated_at=None,
        )

    def test_reclaims_a_long_abandoned_stage(self):
        from app.ai.workflows.assessment.service import _reclaim_stale

        workflow = self._workflow()
        db = _FakeDB(_stage(StageStatus.RUNNING, 100_000))
        assert _reclaim_stale(db, workflow) is True
        assert workflow.state == WorkflowState.FAILED.value
        assert "restarted" in workflow.error
        assert db.committed

    def test_leaves_a_recently_started_stage_alone(self):
        from app.ai.workflows.assessment.service import _reclaim_stale

        workflow = self._workflow()
        db = _FakeDB(_stage(StageStatus.RUNNING, 5))
        assert _reclaim_stale(db, workflow) is False
        assert workflow.state == WorkflowState.IN_PROGRESS.value

    def test_ignores_workflows_that_are_not_in_progress(self):
        from app.ai.workflows.assessment.service import _reclaim_stale

        workflow = self._workflow()
        workflow.state = WorkflowState.AWAITING_APPROVAL.value
        db = _FakeDB(_stage(StageStatus.RUNNING, 100_000))
        assert _reclaim_stale(db, workflow) is False

    def test_threshold_exceeds_the_run_timeout(self):
        """The margin matters: reclaiming at or below the timeout would kill
        stages that are still legitimately running."""
        from app.ai.config import ai_settings
        from app.ai.workflows.assessment.service import _stale_after

        assert _stale_after() > timedelta(seconds=ai_settings.run_timeout_seconds)


class TestGenerationReclamation:
    def test_reclaims_an_abandoned_generation(self):
        from app.ai.workflows.assessment.materialization import _reclaim_stale

        row = SimpleNamespace(
            status=GenerationStatus.GENERATING.value,
            created_at=datetime.now(timezone.utc) - timedelta(seconds=100_000),
            error=None,
        )
        db = _FakeDB(None)
        _reclaim_stale(db, [row])
        assert row.status == GenerationStatus.FAILED.value
        assert "restarted" in row.error

    def test_leaves_a_fresh_generation_running(self):
        from app.ai.workflows.assessment.materialization import _reclaim_stale

        row = SimpleNamespace(
            status=GenerationStatus.GENERATING.value,
            created_at=datetime.now(timezone.utc),
            error=None,
        )
        _reclaim_stale(_FakeDB(None), [row])
        assert row.status == GenerationStatus.GENERATING.value

    def test_ignores_a_finished_generation(self):
        from app.ai.workflows.assessment.materialization import _reclaim_stale

        row = SimpleNamespace(
            status=GenerationStatus.PUBLISHED.value,
            created_at=datetime.now(timezone.utc) - timedelta(seconds=100_000),
            error=None,
        )
        _reclaim_stale(_FakeDB(None), [row])
        assert row.status == GenerationStatus.PUBLISHED.value
