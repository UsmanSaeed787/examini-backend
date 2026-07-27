"""Unit tests for the Assessment Intelligence workflow (pure parts:
state machine, checkpoint policy, pure stage logic, registry, schemas)."""
import pytest

from app.ai.workflows.assessment.domain import (
    DEFAULT_PIPELINE,
    ApprovalMode,
    StageKey,
    StageStatus,
    WorkflowState,
)
from app.ai.workflows.assessment.schemas import (
    ARTIFACT_TYPES,
    CurriculumOutline,
    CurriculumUnit,
)
from app.ai.workflows.assessment.stages import (
    AgentStageHandler,
    get_handler,
    normalize_blueprint,
    plan_schedule,
    registered_pipeline,
    review_quality,
)
from app.ai.workflows.assessment.state_machine import (
    checkpoint_required,
    ensure_stage_transition,
    ensure_workflow_transition,
    next_stage,
)
from app.middleware.error_handler import ValidationError


class TestStateMachine:
    def test_legal_workflow_path(self):
        ensure_workflow_transition(WorkflowState.DRAFT, WorkflowState.IN_PROGRESS)
        ensure_workflow_transition(WorkflowState.IN_PROGRESS, WorkflowState.AWAITING_APPROVAL)
        ensure_workflow_transition(WorkflowState.AWAITING_APPROVAL, WorkflowState.IN_PROGRESS)
        ensure_workflow_transition(WorkflowState.AWAITING_APPROVAL, WorkflowState.COMPLETED)

    def test_illegal_workflow_transitions_raise(self):
        with pytest.raises(ValidationError):
            ensure_workflow_transition(WorkflowState.DRAFT, WorkflowState.COMPLETED)
        with pytest.raises(ValidationError):
            ensure_workflow_transition(WorkflowState.COMPLETED, WorkflowState.IN_PROGRESS)
        with pytest.raises(ValidationError):
            ensure_workflow_transition(WorkflowState.CANCELLED, WorkflowState.IN_PROGRESS)

    def test_legal_stage_path(self):
        ensure_stage_transition(StageStatus.PENDING, StageStatus.RUNNING)
        ensure_stage_transition(StageStatus.RUNNING, StageStatus.IN_REVIEW)
        ensure_stage_transition(StageStatus.IN_REVIEW, StageStatus.REJECTED)
        ensure_stage_transition(StageStatus.REJECTED, StageStatus.PENDING)
        ensure_stage_transition(StageStatus.IN_REVIEW, StageStatus.APPROVED)

    def test_illegal_stage_transitions_raise(self):
        with pytest.raises(ValidationError):
            ensure_stage_transition(StageStatus.PENDING, StageStatus.APPROVED)
        with pytest.raises(ValidationError):
            ensure_stage_transition(StageStatus.APPROVED, StageStatus.PENDING)

    def test_checkpoint_policy(self):
        first, last = DEFAULT_PIPELINE[0], DEFAULT_PIPELINE[-1]
        assert checkpoint_required(ApprovalMode.EVERY_STAGE, first, DEFAULT_PIPELINE)
        assert checkpoint_required(ApprovalMode.EVERY_STAGE, last, DEFAULT_PIPELINE)
        assert not checkpoint_required(ApprovalMode.FINAL_ONLY, first, DEFAULT_PIPELINE)
        assert checkpoint_required(ApprovalMode.FINAL_ONLY, last, DEFAULT_PIPELINE)
        assert not checkpoint_required(ApprovalMode.NONE, last, DEFAULT_PIPELINE)

    def test_next_stage_ordering(self):
        assert next_stage(StageKey.CURRICULUM_ANALYSIS, DEFAULT_PIPELINE) == StageKey.ASSESSMENT_DESIGN
        assert next_stage(StageKey.SCHEDULING, DEFAULT_PIPELINE) is None


class TestBlueprintNormalization:
    def test_valid_config(self):
        bp = normalize_blueprint({"total": 10, "easy": 4, "medium": 4, "hard": 2, "mcq": 10})
        assert bp.total_questions == 10
        assert bp.difficulty_mix == {"easy": 4, "medium": 4, "hard": 2}
        assert bp.type_mix == {"mcq": 10}
        assert bp.estimated_total_points == 10.0
        assert bp.validation_errors == []

    def test_invalid_config_captured_not_raised(self):
        bp = normalize_blueprint({"total": 10, "easy": 1, "medium": 1, "hard": 1})
        assert bp.validation_errors  # sums mismatch recorded, pipeline continues


class TestQualityReview:
    def _outline(self, parseable=True):
        return CurriculumOutline(
            class_id="c", class_name="Grade 10",
            units=[CurriculumUnit(material_id="m", title="Notes", file_type="pdf" if parseable else "png", parseable=parseable)],
        )

    def test_passes_on_clean_inputs(self):
        report = review_quality(self._outline(), normalize_blueprint({"total": 5}))
        assert report.passed

    def test_blocker_on_config_errors(self):
        report = review_quality(self._outline(), normalize_blueprint({}))
        assert not report.passed

    def test_blocker_when_nothing_parseable(self):
        report = review_quality(self._outline(parseable=False), normalize_blueprint({"total": 5}))
        assert not report.passed
        assert any("extractable text" in f.message for f in report.findings)


class TestScheduling:
    def test_blocker_on_inverted_window(self):
        plan = plan_schedule({"proposed_start": "2026-08-01T10:00:00", "proposed_end": "2026-08-01T09:00:00"})
        assert any(f.severity == "blocker" for f in plan.findings)

    def test_blocker_when_duration_exceeds_window(self):
        plan = plan_schedule({
            "duration_minutes": 120,
            "proposed_start": "2026-08-01T10:00:00",
            "proposed_end": "2026-08-01T11:00:00",
        })
        assert any("exceeds the exam window" in f.message for f in plan.findings)

    def test_warning_without_duration(self):
        plan = plan_schedule({})
        assert any(f.severity == "warning" for f in plan.findings)


class TestRegistry:
    def test_every_pipeline_stage_has_handler(self):
        assert registered_pipeline() == DEFAULT_PIPELINE
        for stage in DEFAULT_PIPELINE:
            assert get_handler(stage).key == stage

    def test_every_stage_has_artifact_type(self):
        for stage in DEFAULT_PIPELINE:
            assert stage in ARTIFACT_TYPES

    def test_agent_adapter_targets_stage_artifact(self):
        adapter = AgentStageHandler(StageKey.CURRICULUM_ANALYSIS, "curriculum_analyst")
        assert adapter.key == StageKey.CURRICULUM_ANALYSIS
        assert adapter.agent_key == "curriculum_analyst"
