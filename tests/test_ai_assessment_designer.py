"""Unit tests for the Assessment Designer (Phase 7): output schema, guardrail
validation, cross-artifact mix consistency, the deterministic merge, the
hybrid stage handler (fallbacks + agent path, agent run mocked), and
flag-driven registration. Also asserts the phase's hard constraints: no
tools (no DB access) and no scheduling fields."""
from uuid import uuid4

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.ai.config import ai_settings
from app.ai.guardrails.output import design_consistency_errors, validate_assessment_design
from app.ai.schemas.outputs import (
    AssessmentDesignOutput,
    BloomLevel,
    TopicAllocation,
    TopicAnalysis,
)
from app.ai.schemas.runs import RunOutcome
from app.ai.workflows.assessment.domain import StageKey
from app.ai.workflows.assessment.schemas import AssessmentBlueprint, CurriculumOutline
from app.ai.workflows.assessment.stages import (
    AssessmentDesignerHandler,
    AssessmentDesignHandler,
    StageContext,
    configure_design_stage,
    get_handler,
    merge_blueprint,
    normalize_blueprint,
)

TOPIC_A = "Photosynthesis"
TOPIC_B = "Cell Division"


def _topics() -> list[TopicAnalysis]:
    return [
        TopicAnalysis(
            title=TOPIC_A,
            learning_outcomes=["Describe the light reactions"],
            bloom_levels=[BloomLevel.UNDERSTAND, BloomLevel.APPLY],
            emphasis="high",
        ),
        TopicAnalysis(
            title=TOPIC_B,
            learning_outcomes=["Compare mitosis and meiosis"],
            bloom_levels=[BloomLevel.ANALYZE],
            emphasis="medium",
        ),
    ]


def _outline(with_topics=True) -> CurriculumOutline:
    return CurriculumOutline(
        class_id=str(uuid4()),
        class_name="Grade 10 Biology",
        units=[],
        topics=_topics() if with_topics else [],
        summary="Covers cell biology." if with_topics else None,
    )


def _design(**overrides) -> AssessmentDesignOutput:
    defaults = dict(
        topic_allocations=[
            TopicAllocation(
                topic_title=TOPIC_A,
                question_count=6,
                question_types={"mcq": 6},
                bloom_levels=[BloomLevel.UNDERSTAND],
            ),
            TopicAllocation(
                topic_title=TOPIC_B,
                question_count=4,
                question_types={"mcq": 4},
                bloom_levels=[BloomLevel.ANALYZE],
            ),
        ],
        rationale="Weighted toward the more heavily emphasized topic.",
    )
    defaults.update(overrides)
    return AssessmentDesignOutput(**defaults)


def _ctx(**overrides) -> StageContext:
    defaults = dict(
        workflow_id=uuid4(),
        user_id=uuid4(),
        role="teacher",
        class_id=uuid4(),
        config={"question_config": {"total": 10, "mcq": 10}},
        revision=1,
        prior_artifacts={StageKey.CURRICULUM_ANALYSIS.value: _outline().model_dump(mode="json")},
    )
    defaults.update(overrides)
    return StageContext(**defaults)


class TestOutputSchema:
    def test_allocation_requires_positive_count(self):
        with pytest.raises(PydanticValidationError):
            TopicAllocation(topic_title=TOPIC_A, question_count=0)

    def test_bloom_vocabulary_enforced(self):
        with pytest.raises(PydanticValidationError):
            TopicAllocation(topic_title=TOPIC_A, question_count=1, bloom_levels=["memorize"])

    def test_design_output_has_no_scheduling_fields(self):
        """Phase 7 constraint: the designer never schedules."""
        fields = set(AssessmentDesignOutput.model_fields) | set(TopicAllocation.model_fields)
        assert not fields & {"duration_minutes", "start_date", "end_date", "proposed_start"}

    def test_blueprint_backwards_compatible(self):
        skeleton = normalize_blueprint({"total": 10})
        assert skeleton.topic_allocations == [] and skeleton.rationale is None


class TestGuardrail:
    def test_valid_design_passes(self):
        assert validate_assessment_design(_design(), _topics(), 10) == []

    def test_empty_allocations_rejected(self):
        output = AssessmentDesignOutput(topic_allocations=[], rationale="none")
        assert validate_assessment_design(output, _topics(), 10) == [
            "The design contains no topic allocations"
        ]

    def test_invented_topic_rejected(self):
        output = _design(
            topic_allocations=[TopicAllocation(topic_title="Astrophysics", question_count=10)]
        )
        errors = validate_assessment_design(output, _topics(), 10)
        assert any("not a topic from the curriculum outline" in e for e in errors)

    def test_allocation_total_must_match_request(self):
        errors = validate_assessment_design(_design(), _topics(), 12)
        assert any("Allocations sum to 10 questions, expected 12" in e for e in errors)

    def test_per_type_counts_must_sum_to_allocation(self):
        output = _design(
            topic_allocations=[
                TopicAllocation(topic_title=TOPIC_A, question_count=6, question_types={"mcq": 3})
            ]
        )
        errors = validate_assessment_design(output, _topics(), 6)
        assert any("per-type counts sum to 3" in e for e in errors)

    def test_unknown_question_type_rejected(self):
        output = _design(
            topic_allocations=[
                TopicAllocation(topic_title=TOPIC_A, question_count=2, question_types={"essay": 2})
            ]
        )
        errors = validate_assessment_design(output, _topics(), 2)
        assert any("unknown question type" in e for e in errors)

    def test_bloom_levels_cannot_exceed_curriculum(self):
        output = _design(
            topic_allocations=[
                TopicAllocation(
                    topic_title=TOPIC_A, question_count=10, bloom_levels=[BloomLevel.CREATE]
                )
            ]
        )
        errors = validate_assessment_design(output, _topics(), 10)
        assert any("exceed what the curriculum analysis found" in e for e in errors)

    def test_duplicate_topic_allocation_rejected(self):
        output = _design(
            topic_allocations=[
                TopicAllocation(topic_title=TOPIC_A, question_count=5),
                TopicAllocation(topic_title=TOPIC_A, question_count=5),
            ]
        )
        errors = validate_assessment_design(output, _topics(), 10)
        assert any("duplicated allocation" in e for e in errors)


class TestConsistency:
    def test_matching_mix_has_no_errors(self):
        assert design_consistency_errors(_design(), {"mcq": 10}) == []

    def test_mix_contradiction_reported(self):
        errors = design_consistency_errors(_design(), {"mcq": 6, "short_answer": 4})
        assert any("short_answer" in e for e in errors)

    def test_skipped_when_types_not_declared(self):
        output = _design(
            topic_allocations=[TopicAllocation(topic_title=TOPIC_A, question_count=10)]
        )
        assert design_consistency_errors(output, {"mcq": 10}) == []


class TestMerge:
    def test_agent_contributes_only_design_half(self):
        skeleton = normalize_blueprint({"total": 10, "mcq": 10})
        merged = merge_blueprint(skeleton, _design())
        assert merged.total_questions == 10                       # skeleton untouched
        assert merged.type_mix == {"mcq": 10}
        assert merged.estimated_total_points == skeleton.estimated_total_points
        assert [a.topic_title for a in merged.topic_allocations] == [TOPIC_A, TOPIC_B]
        assert merged.rationale.startswith("Weighted")

    def test_mix_contradiction_lands_in_validation_errors(self):
        skeleton = normalize_blueprint({"total": 10, "mcq": 6, "short_answer": 4})
        merged = merge_blueprint(skeleton, _design())
        assert any("short_answer" in e for e in merged.validation_errors)


class TestHandler:
    async def test_fallback_when_config_invalid(self, monkeypatch):
        async def _must_not_run(*a, **k):  # pragma: no cover - failure signal
            raise AssertionError("agent must not run for an invalid config")

        monkeypatch.setattr(AssessmentDesignerHandler, "_run_agent", _must_not_run)
        ctx = _ctx(config={"question_config": {"total": 10, "easy": 1}})  # mix mismatch
        result = await AssessmentDesignerHandler().execute(ctx)
        assert result.validation_errors and result.topic_allocations == []

    async def test_fallback_when_outline_has_no_topics(self, monkeypatch):
        async def _must_not_run(*a, **k):  # pragma: no cover - failure signal
            raise AssertionError("agent must not run without curriculum topics")

        monkeypatch.setattr(AssessmentDesignerHandler, "_run_agent", _must_not_run)
        ctx = _ctx(
            prior_artifacts={
                StageKey.CURRICULUM_ANALYSIS.value: _outline(with_topics=False).model_dump(mode="json")
            }
        )
        result = await AssessmentDesignerHandler().execute(ctx)
        assert result.topic_allocations == []

    async def test_fallback_when_curriculum_stage_missing(self):
        result = await AssessmentDesignerHandler().execute(_ctx(prior_artifacts={}))
        assert result.total_questions == 10 and result.topic_allocations == []

    async def test_agent_path_merges_and_records_run_id(self, monkeypatch):
        run_id = uuid4()
        captured = {}

        async def fake_execute_run(run_context, agent_key, user_input, **kw):
            captured["agent_key"] = agent_key
            captured["input"] = user_input
            captured["extra"] = run_context.extra
            return RunOutcome(
                run_id=run_id, agent_key=agent_key, status="completed", final_output=_design()
            )

        import app.ai.runtime.runner as runner_module

        monkeypatch.setattr(runner_module, "execute_run", fake_execute_run)
        ctx = _ctx(rejection_notes="favour applied questions")
        result = await AssessmentDesignerHandler().execute(ctx)

        assert captured["agent_key"] == "assessment_designer"
        assert TOPIC_A in captured["input"]                          # outline topics fed in
        assert "favour applied questions" in captured["input"]       # rejection feedback fed back
        assert captured["extra"]["total_questions"] == 10            # guardrail inputs
        assert len(captured["extra"]["topics"]) == 2
        assert captured["extra"]["class_id"] == str(ctx.class_id)    # Context Engine hints
        assert len(result.topic_allocations) == 2
        assert ctx.run_id == run_id                                  # ai_runs linkage


class TestRegistration:
    def test_flag_off_uses_deterministic_handler(self, monkeypatch):
        monkeypatch.setattr(ai_settings, "use_assessment_designer", False)
        configure_design_stage()
        assert isinstance(get_handler(StageKey.ASSESSMENT_DESIGN), AssessmentDesignHandler)

    def test_flag_on_uses_agent_handler(self, monkeypatch):
        monkeypatch.setattr(ai_settings, "enabled", True)
        monkeypatch.setattr(ai_settings, "use_assessment_designer", True)
        configure_design_stage()
        try:
            assert isinstance(get_handler(StageKey.ASSESSMENT_DESIGN), AssessmentDesignerHandler)
        finally:
            monkeypatch.setattr(ai_settings, "use_assessment_designer", False)
            configure_design_stage()

    def test_agent_contract_and_no_database_reach(self):
        from app.ai.agents.registry import discover, get_spec

        discover(force=True)
        spec = get_spec("assessment_designer")
        assert spec.allowed_roles == ("teacher",)
        assert spec.structured_output == "AssessmentDesignOutput"
        assert "assessment" in spec.supported_workflows
        assert spec.api_invocable is False
        assert spec.required_tools == ()          # no tools -> no database access
        agent = spec.factory()
        assert agent.tools == [] and agent.output_guardrails
