"""Unit tests for deterministic mix adjustment (#4-lite).

The teacher changes the numbers; everything derived from them recomputes
without a model call. The invariants that matter: which stages are affected,
that agent-backed handlers really do skip their agent, and that an adjustment
cannot quietly leave an approved plan describing figures that changed.
"""
import pytest

from app.ai.workflows.assessment.domain import (
    ADJUSTABLE_FROM,
    DEFAULT_PIPELINE,
    DETERMINISTIC_RERUN_KEY,
    CheckpointDecision,
    GenerationStatus,
    StageKey,
    StageStatus,
)
from app.ai.workflows.assessment.schemas import (
    AssessmentBlueprint,
    CurriculumOutline,
    CurriculumUnit,
)
from app.ai.workflows.assessment.stages import (
    AssessmentDesignerHandler,
    DifficultyAnalyzerHandler,
    QualityReviewerHandler,
    StageContext,
)
from app.ai.workflows.assessment.state_machine import ensure_stage_invalidation
from app.middleware.error_handler import ValidationError
from uuid import uuid4


def _ctx(**overrides) -> StageContext:
    defaults = dict(
        workflow_id=uuid4(),
        user_id=uuid4(),
        role="teacher",
        class_id=uuid4(),
        config={"question_config": {"total": 8, "mcq": 8, "easy": 4, "medium": 4}},
        revision=1,
        deterministic_only=True,
    )
    defaults.update(overrides)
    return StageContext(**defaults)


class TestScope:
    def test_adjustment_starts_at_the_design_stage(self):
        assert ADJUSTABLE_FROM == StageKey.ASSESSMENT_DESIGN

    def test_curriculum_analysis_is_never_recomputed(self):
        """The materials did not change, so re-reading them would spend a model
        call to reproduce the identical inventory."""
        affected = DEFAULT_PIPELINE[DEFAULT_PIPELINE.index(ADJUSTABLE_FROM):]
        assert StageKey.CURRICULUM_ANALYSIS not in affected

    def test_everything_derived_from_the_mix_is_recomputed(self):
        affected = DEFAULT_PIPELINE[DEFAULT_PIPELINE.index(ADJUSTABLE_FROM):]
        assert set(affected) == {
            StageKey.ASSESSMENT_DESIGN,   # is the mix
            StageKey.QUALITY_REVIEW,      # checks the blueprint
            StageKey.DIFFICULTY_ANALYSIS, # reads the target distribution
            StageKey.SCHEDULING,          # estimates duration from the types
        }


class TestInvalidationGuard:
    def test_a_running_stage_cannot_be_invalidated(self):
        """Editing under a stage that is mid-flight would race its own result."""
        with pytest.raises(ValidationError):
            ensure_stage_invalidation(StageStatus.RUNNING)

    def test_settled_stages_can_be_reopened(self):
        for status in (
            StageStatus.APPROVED,
            StageStatus.IN_REVIEW,
            StageStatus.PENDING,
            StageStatus.FAILED,
        ):
            ensure_stage_invalidation(status)  # must not raise


class TestHandlersSkipTheirAgent:
    """Each agent-backed handler must recompute from its deterministic core.
    If any of these called out, an adjustment would cost a model run and the
    whole point of the feature is lost."""

    async def test_designer_returns_the_skeleton(self):
        outline = CurriculumOutline(
            class_id=str(uuid4()),
            class_name="Physics",
            units=[CurriculumUnit(material_id=str(uuid4()), title="M", parseable=True)],
            topics=[],
        )
        ctx = _ctx(
            prior_artifacts={StageKey.CURRICULUM_ANALYSIS.value: outline.model_dump(mode="json")}
        )
        result = await AssessmentDesignerHandler().execute(ctx)
        assert result.total_questions == 8
        # no agent ran, so no allocations and no run linked
        assert result.topic_allocations == []
        assert ctx.run_id is None

    async def test_quality_reviewer_returns_the_deterministic_report(self):
        outline = CurriculumOutline(
            class_id=str(uuid4()),
            class_name="Physics",
            units=[CurriculumUnit(material_id=str(uuid4()), title="M", parseable=True)],
        )
        blueprint = AssessmentBlueprint(
            total_questions=8,
            type_mix={"mcq": 8},
            difficulty_mix={"easy": 4, "medium": 4},
            estimated_total_points=8.0,
        )
        ctx = _ctx(
            prior_artifacts={
                StageKey.CURRICULUM_ANALYSIS.value: outline.model_dump(mode="json"),
                StageKey.ASSESSMENT_DESIGN.value: blueprint.model_dump(mode="json"),
            }
        )
        report = await QualityReviewerHandler().execute(ctx)
        assert report.dimension_verdicts == []  # agent commentary dropped, not stale
        assert ctx.run_id is None

    async def test_difficulty_analyzer_returns_statistics_only(self, monkeypatch):
        from app.ai.workflows.assessment import stages as stage_module

        monkeypatch.setattr(
            stage_module,
            "load_historical_difficulty",
            lambda _user_id: stage_module.HistoricalDifficulty(),
        )
        blueprint = AssessmentBlueprint(
            total_questions=8,
            type_mix={"mcq": 8},
            difficulty_mix={"easy": 4, "medium": 4},
            estimated_total_points=8.0,
        )
        ctx = _ctx(
            prior_artifacts={StageKey.ASSESSMENT_DESIGN.value: blueprint.model_dump(mode="json")}
        )
        profile = await DifficultyAnalyzerHandler().execute(ctx)
        assert profile.target_distribution  # statistics still computed
        assert profile.calibration is None   # interpretation not invented
        assert ctx.run_id is None


class _FakeGenQuery:
    def __init__(self, rows):
        self._rows = rows

    def filter(self, *_a, **_k):
        return self

    def order_by(self, *_a, **_k):
        return self

    def all(self):
        return self._rows


class _FakeGenDB:
    def __init__(self, rows):
        self._rows = rows

    def query(self, *_a):
        return _FakeGenQuery(self._rows)


def _gen(status: GenerationStatus, attempt: int = 1):
    from types import SimpleNamespace

    return SimpleNamespace(status=status.value, attempt=attempt)


class TestAdjustAfterCompletion:
    """Approving the plan must not be the moment the numbers freeze — the
    teacher is then looking at the Generate step, which is exactly when
    'actually, make it 12' occurs to them."""

    def test_draft_generation_is_superseded_not_blocked(self):
        from app.ai.workflows.assessment.service import _supersede_generations

        row = _gen(GenerationStatus.GENERATED)
        _supersede_generations(_FakeGenDB([row]), uuid4())
        assert row.status == GenerationStatus.SUPERSEDED.value

    def test_failed_attempt_is_also_superseded(self):
        from app.ai.workflows.assessment.service import _supersede_generations

        row = _gen(GenerationStatus.FAILED)
        _supersede_generations(_FakeGenDB([row]), uuid4())
        assert row.status == GenerationStatus.SUPERSEDED.value

    def test_published_assessment_refuses(self):
        """A live exam's questions came from this mix; silently changing it
        underneath students is not an option."""
        from app.ai.workflows.assessment.service import _supersede_generations

        with pytest.raises(ValidationError, match="already published"):
            _supersede_generations(_FakeGenDB([_gen(GenerationStatus.PUBLISHED)]), uuid4())

    def test_in_flight_generation_refuses(self):
        from app.ai.workflows.assessment.service import _supersede_generations

        with pytest.raises(ValidationError):
            _supersede_generations(_FakeGenDB([_gen(GenerationStatus.GENERATING)]), uuid4())

    def test_no_generations_is_a_no_op(self):
        from app.ai.workflows.assessment.service import _supersede_generations

        _supersede_generations(_FakeGenDB([]), uuid4())  # must not raise

    def test_latest_attempt_decides(self):
        """Ordered by attempt desc, so a superseded older draft never masks a
        published newer one."""
        from app.ai.workflows.assessment.service import _supersede_generations

        rows = [_gen(GenerationStatus.PUBLISHED, 2), _gen(GenerationStatus.SUPERSEDED, 1)]
        with pytest.raises(ValidationError, match="already published"):
            _supersede_generations(_FakeGenDB(rows), uuid4())


class TestAuditAndFlags:
    def test_adjusted_is_a_distinct_decision(self):
        assert CheckpointDecision.ADJUSTED.value == "adjusted"
        assert CheckpointDecision.ADJUSTED not in (
            CheckpointDecision.APPROVED,
            CheckpointDecision.REJECTED,
        )

    def test_deterministic_flag_key_is_namespaced(self):
        """It shares the config dict with the teacher's own settings, so it must
        not collide with a real key."""
        assert DETERMINISTIC_RERUN_KEY.startswith("_")

    def test_agent_adapter_refuses_deterministic_mode(self):
        """AgentStageHandler has no deterministic core, so it must fail loudly
        rather than silently run a model during a 'free' recompute."""
        from app.ai.workflows.assessment.stages import AgentStageHandler

        handler = AgentStageHandler(StageKey.CURRICULUM_ANALYSIS, "curriculum_analyst")
        with pytest.raises(ValidationError):
            import asyncio

            asyncio.run(handler.execute(_ctx()))
