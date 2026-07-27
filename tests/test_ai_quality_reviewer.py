"""Unit tests for the Quality Reviewer (Phase 8): output schema, guardrail
(all five dimensions covered, negative verdicts substantiated), the ADD-ONLY
blocker merge rule, policy facts, the hybrid stage handler, and flag-driven
registration. Also asserts the phase constraint: no workflow orchestration."""
from uuid import uuid4

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.ai.config import ai_settings
from app.ai.guardrails.output import validate_quality_review
from app.ai.schemas.outputs import (
    BloomLevel,
    DimensionVerdict,
    QualityDimension,
    QualityObservation,
    QualityReviewOutput,
    TopicAllocation,
    TopicAnalysis,
)
from app.ai.schemas.runs import RunOutcome
from app.ai.workflows.assessment.domain import StageKey
from app.ai.workflows.assessment.schemas import (
    AssessmentBlueprint,
    CurriculumOutline,
    CurriculumUnit,
    Finding,
    QualityReport,
)
from app.ai.workflows.assessment.stages import (
    QualityReviewerHandler,
    QualityReviewHandler,
    StageContext,
    _policy_facts,
    configure_quality_stage,
    get_handler,
    merge_quality_report,
)
from app.middleware.error_handler import ValidationError

TOPIC = "Photosynthesis"


def _verdicts(**overrides) -> list[DimensionVerdict]:
    verdicts = {
        d: DimensionVerdict(dimension=d, verdict="pass", comment="fine")
        for d in QualityDimension
    }
    for dimension, verdict in overrides.items():
        d = QualityDimension(dimension)
        verdicts[d] = DimensionVerdict(dimension=d, verdict=verdict, comment="noted")
    return list(verdicts.values())


def _review(observations=None, **verdict_overrides) -> QualityReviewOutput:
    return QualityReviewOutput(
        dimension_verdicts=_verdicts(**verdict_overrides),
        observations=observations or [],
        summary="Overall the blueprint is sound.",
    )


def _outline(with_topics=True) -> CurriculumOutline:
    return CurriculumOutline(
        class_id=str(uuid4()),
        class_name="Grade 10 Biology",
        units=[
            CurriculumUnit(material_id=str(uuid4()), title="Notes", file_type="pdf", parseable=True)
        ],
        topics=[
            TopicAnalysis(
                title=TOPIC,
                learning_outcomes=["Describe the light reactions"],
                bloom_levels=[BloomLevel.UNDERSTAND],
            )
        ]
        if with_topics
        else [],
        summary="Covers cell biology." if with_topics else None,
    )


def _blueprint(errors=None) -> AssessmentBlueprint:
    return AssessmentBlueprint(
        total_questions=10,
        type_mix={"mcq": 10},
        difficulty_mix={"easy": 5, "medium": 5},
        default_points=1.0,
        estimated_total_points=10.0,
        validation_errors=errors or [],
        topic_allocations=[TopicAllocation(topic_title=TOPIC, question_count=10)],
    )


def _ctx(**overrides) -> StageContext:
    defaults = dict(
        workflow_id=uuid4(),
        user_id=uuid4(),
        role="teacher",
        class_id=uuid4(),
        config={},
        revision=1,
        prior_artifacts={
            StageKey.CURRICULUM_ANALYSIS.value: _outline().model_dump(mode="json"),
            StageKey.ASSESSMENT_DESIGN.value: _blueprint().model_dump(mode="json"),
        },
    )
    defaults.update(overrides)
    return StageContext(**defaults)


class TestOutputSchema:
    def test_verdict_vocabulary_enforced(self):
        with pytest.raises(PydanticValidationError):
            DimensionVerdict(dimension=QualityDimension.COVERAGE, verdict="maybe", comment="x")

    def test_severity_vocabulary_enforced(self):
        with pytest.raises(PydanticValidationError):
            QualityObservation(
                dimension=QualityDimension.COVERAGE, severity="critical", message="x"
            )

    def test_output_has_no_orchestration_fields(self):
        """Phase 8 constraint: the reviewer never orchestrates the workflow."""
        fields = set(QualityReviewOutput.model_fields) | set(DimensionVerdict.model_fields)
        assert not fields & {"passed", "approved", "next_stage", "stage_status", "decision"}

    def test_report_backwards_compatible(self):
        report = QualityReport(passed=True)
        assert report.dimension_verdicts == [] and report.summary is None


class TestGuardrail:
    def test_complete_review_passes(self):
        assert validate_quality_review(_review()) == []

    def test_empty_verdicts_rejected(self):
        output = QualityReviewOutput(dimension_verdicts=[], summary="s")
        assert validate_quality_review(output) == ["The review contains no dimension verdicts"]

    def test_missing_dimension_rejected(self):
        partial = [v for v in _verdicts() if v.dimension != QualityDimension.BLOOM_TAXONOMY]
        output = QualityReviewOutput(dimension_verdicts=partial, summary="s")
        errors = validate_quality_review(output)
        assert any("bloom_taxonomy" in e for e in errors)

    def test_duplicate_dimension_rejected(self):
        verdicts = _verdicts()
        verdicts.append(
            DimensionVerdict(dimension=QualityDimension.COVERAGE, verdict="fail", comment="dup")
        )
        output = QualityReviewOutput(dimension_verdicts=verdicts, summary="s")
        errors = validate_quality_review(output)
        assert any("more than one verdict" in e for e in errors)

    def test_unsupported_negative_verdict_rejected(self):
        output = _review(coverage="fail")  # no observation backing it
        errors = validate_quality_review(output)
        assert any("no supporting observation" in e for e in errors)

    def test_substantiated_negative_verdict_passes(self):
        output = _review(
            coverage="fail",
            observations=[
                QualityObservation(
                    dimension=QualityDimension.COVERAGE,
                    severity="blocker",
                    message="Half the syllabus is untested",
                )
            ],
        )
        assert validate_quality_review(output) == []

    def test_not_assessable_needs_no_observation(self):
        assert validate_quality_review(_review(coverage="not_assessable")) == []


class TestAddOnlyMerge:
    def test_agent_can_add_a_blocker(self):
        deterministic = QualityReport(passed=True, findings=[])
        review = _review(
            coverage="fail",
            observations=[
                QualityObservation(
                    dimension=QualityDimension.COVERAGE, severity="blocker", message="gap"
                )
            ],
        )
        merged = merge_quality_report(deterministic, review)
        assert merged.passed is False
        assert any("[coverage] gap" in f.message for f in merged.findings)

    def test_agent_cannot_clear_a_deterministic_blocker(self):
        """The critical safety property: an all-pass review cannot rescue a
        report the platform's own checks failed."""
        deterministic = QualityReport(
            passed=False,
            findings=[
                Finding(severity="blocker", message="config invalid", stage=StageKey.QUALITY_REVIEW)
            ],
        )
        merged = merge_quality_report(deterministic, _review())
        assert merged.passed is False
        assert any(f.message == "config invalid" for f in merged.findings)

    def test_warnings_do_not_fail_the_report(self):
        deterministic = QualityReport(passed=True, findings=[])
        review = _review(
            difficulty_balance="concerns",
            observations=[
                QualityObservation(
                    dimension=QualityDimension.DIFFICULTY_BALANCE,
                    severity="warning",
                    message="skewed easy",
                )
            ],
        )
        merged = merge_quality_report(deterministic, review)
        assert merged.passed is True
        assert len(merged.dimension_verdicts) == len(QualityDimension)
        assert merged.summary

    def test_deterministic_findings_preserved(self):
        deterministic = QualityReport(
            passed=True,
            findings=[Finding(severity="info", message="fyi", stage=StageKey.QUALITY_REVIEW)],
        )
        merged = merge_quality_report(deterministic, _review())
        assert merged.findings[0].message == "fyi"


class TestPolicyFacts:
    def test_policies_derived_from_platform(self):
        facts = _policy_facts(_ctx())
        assert facts["pass_threshold_percent"] == 50.0
        assert facts["max_questions_per_exam"] >= 1
        assert {"min_percentage": 90.0, "grade": "A+"} in facts["grade_bands"]


class TestHandler:
    async def test_missing_artifacts_fail_cleanly(self):
        with pytest.raises(ValidationError):
            await QualityReviewerHandler().execute(_ctx(prior_artifacts={}))

    async def test_fallback_when_deterministic_blockers_exist(self, monkeypatch):
        async def _must_not_run(*a, **k):  # pragma: no cover - failure signal
            raise AssertionError("agent must not run when structural checks already failed")

        monkeypatch.setattr(QualityReviewerHandler, "_run_agent", _must_not_run)
        ctx = _ctx(
            prior_artifacts={
                StageKey.CURRICULUM_ANALYSIS.value: _outline().model_dump(mode="json"),
                StageKey.ASSESSMENT_DESIGN.value: _blueprint(
                    errors=["total mismatch"]
                ).model_dump(mode="json"),
            }
        )
        result = await QualityReviewerHandler().execute(ctx)
        assert result.passed is False and result.dimension_verdicts == []

    async def test_agent_path_merges_and_records_run_id(self, monkeypatch):
        run_id = uuid4()
        captured = {}

        async def fake_execute_run(run_context, agent_key, user_input, **kw):
            captured["agent_key"] = agent_key
            captured["input"] = user_input
            captured["extra"] = run_context.extra
            return RunOutcome(
                run_id=run_id, agent_key=agent_key, status="completed", final_output=_review()
            )

        import app.ai.runtime.runner as runner_module

        monkeypatch.setattr(runner_module, "execute_run", fake_execute_run)
        ctx = _ctx(rejection_notes="check higher-order coverage")
        result = await QualityReviewerHandler().execute(ctx)

        assert captured["agent_key"] == "quality_reviewer"
        assert "pass_threshold_percent" in captured["input"]        # institution policies fed in
        assert TOPIC in captured["input"]                           # curriculum + blueprint fed in
        assert "check higher-order coverage" in captured["input"]   # rejection feedback fed back
        assert captured["extra"]["class_id"] == str(ctx.class_id)   # Context Engine hints
        assert result.passed is True
        assert len(result.dimension_verdicts) == len(QualityDimension)
        assert ctx.run_id == run_id                                 # ai_runs linkage

    async def test_topicless_outline_flagged_as_not_assessable(self, monkeypatch):
        async def fake_execute_run(run_context, agent_key, user_input, **kw):
            assert "not_assessable" in user_input
            return RunOutcome(
                run_id=uuid4(), agent_key=agent_key, status="completed", final_output=_review()
            )

        import app.ai.runtime.runner as runner_module

        monkeypatch.setattr(runner_module, "execute_run", fake_execute_run)
        ctx = _ctx(
            prior_artifacts={
                StageKey.CURRICULUM_ANALYSIS.value: _outline(with_topics=False).model_dump(mode="json"),
                StageKey.ASSESSMENT_DESIGN.value: _blueprint().model_dump(mode="json"),
            }
        )
        result = await QualityReviewerHandler().execute(ctx)
        assert result.passed is True


class TestRegistration:
    def test_flag_off_uses_deterministic_handler(self, monkeypatch):
        monkeypatch.setattr(ai_settings, "use_quality_reviewer", False)
        configure_quality_stage()
        assert isinstance(get_handler(StageKey.QUALITY_REVIEW), QualityReviewHandler)

    def test_flag_on_uses_agent_handler(self, monkeypatch):
        monkeypatch.setattr(ai_settings, "enabled", True)
        monkeypatch.setattr(ai_settings, "use_quality_reviewer", True)
        configure_quality_stage()
        try:
            assert isinstance(get_handler(StageKey.QUALITY_REVIEW), QualityReviewerHandler)
        finally:
            monkeypatch.setattr(ai_settings, "use_quality_reviewer", False)
            configure_quality_stage()

    def test_agent_contract_and_no_database_reach(self):
        from app.ai.agents.registry import discover, get_spec

        discover(force=True)
        spec = get_spec("quality_reviewer")
        assert spec.allowed_roles == ("teacher",)
        assert spec.structured_output == "QualityReviewOutput"
        assert "assessment" in spec.supported_workflows
        assert spec.api_invocable is False
        assert spec.required_tools == ()      # no tools -> no database access
        agent = spec.factory()
        assert agent.tools == [] and agent.output_guardrails
