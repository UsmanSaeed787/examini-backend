"""Unit tests for the Curriculum Analyst (Phase 6): output schema, guardrail
validation, the deterministic merge, the hybrid stage handler (fallback and
agent paths — agent run mocked, no LLM), and flag-driven registration."""
from uuid import uuid4

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.ai.config import ai_settings
from app.ai.guardrails.output import validate_curriculum_analysis
from app.ai.schemas.outputs import BloomLevel, CurriculumAnalysisOutput, TopicAnalysis
from app.ai.schemas.runs import RunOutcome
from app.ai.workflows.assessment import stages
from app.ai.workflows.assessment.domain import StageKey
from app.ai.workflows.assessment.schemas import CurriculumOutline, CurriculumUnit, Finding
from app.ai.workflows.assessment.stages import (
    CurriculumAnalysisHandler,
    CurriculumAnalystHandler,
    StageContext,
    configure_curriculum_stage,
    get_handler,
    merge_outline,
)

MATERIAL_ID = str(uuid4())


def _topic(**overrides) -> TopicAnalysis:
    defaults = dict(
        title="Photosynthesis",
        subtopics=["Light reactions"],
        learning_outcomes=["Students will be able to describe the light reactions"],
        bloom_levels=[BloomLevel.UNDERSTAND, BloomLevel.APPLY],
        source_material_ids=[MATERIAL_ID],
        emphasis="high",
    )
    defaults.update(overrides)
    return TopicAnalysis(**defaults)


def _outline(parseable=True, blockers=False) -> CurriculumOutline:
    findings = (
        [Finding(severity="blocker", message="missing", stage=StageKey.CURRICULUM_ANALYSIS)]
        if blockers
        else []
    )
    return CurriculumOutline(
        class_id=str(uuid4()),
        class_name="Grade 10 Biology",
        units=[
            CurriculumUnit(
                material_id=MATERIAL_ID,
                title="Bio Notes",
                file_type="pdf" if parseable else "png",
                parseable=parseable,
            )
        ],
        findings=findings,
    )


def _ctx(**overrides) -> StageContext:
    defaults = dict(
        workflow_id=uuid4(),
        user_id=uuid4(),
        role="teacher",
        class_id=uuid4(),
        config={"material_ids": [MATERIAL_ID]},
        revision=1,
    )
    defaults.update(overrides)
    return StageContext(**defaults)


class TestOutputSchema:
    def test_bloom_vocabulary_enforced(self):
        with pytest.raises(PydanticValidationError):
            TopicAnalysis(title="T", bloom_levels=["memorize"])  # not a Bloom level

    def test_emphasis_pattern_enforced(self):
        with pytest.raises(PydanticValidationError):
            _topic(emphasis="extreme")

    def test_outline_backwards_compatible(self):
        """The deterministic handler's outlines (no topics/summary) still
        validate against the extended artifact contract."""
        outline = _outline()
        assert outline.topics == [] and outline.summary is None


class TestGuardrail:
    def test_valid_analysis_passes(self):
        output = CurriculumAnalysisOutput(topics=[_topic()], summary="Covers photosynthesis.")
        assert validate_curriculum_analysis(output, [MATERIAL_ID]) == []

    def test_empty_topics_rejected(self):
        with pytest.raises(PydanticValidationError):
            CurriculumAnalysisOutput(topics=[], summary="")  # summary min_length too
        output = CurriculumAnalysisOutput(topics=[], summary="x")
        assert validate_curriculum_analysis(output, [MATERIAL_ID]) == [
            "The analysis contains no topics"
        ]

    def test_missing_outcomes_and_bloom_rejected(self):
        output = CurriculumAnalysisOutput(
            topics=[_topic(learning_outcomes=[], bloom_levels=[])], summary="s"
        )
        errors = validate_curriculum_analysis(output, [MATERIAL_ID])
        assert any("no learning outcomes" in e for e in errors)
        assert any("no Bloom" in e for e in errors)

    def test_invented_source_materials_rejected(self):
        output = CurriculumAnalysisOutput(
            topics=[_topic(source_material_ids=["fabricated-id"])], summary="s"
        )
        errors = validate_curriculum_analysis(output, [MATERIAL_ID])
        assert any("unknown material id" in e for e in errors)


class TestMerge:
    def test_agent_contributes_only_analysis_half(self):
        inventory = _outline()
        analysis = CurriculumAnalysisOutput(topics=[_topic()], summary="Scope summary")
        merged = merge_outline(inventory, analysis)
        assert merged.class_name == inventory.class_name          # inventory untouched
        assert merged.units == inventory.units
        assert merged.topics[0].title == "Photosynthesis"          # analysis merged
        assert merged.summary == "Scope summary"


class TestHandler:
    async def test_fallback_on_blockers_skips_agent(self, monkeypatch):
        inventory = _outline(blockers=True)
        monkeypatch.setattr(CurriculumAnalysisHandler, "_run", staticmethod(lambda ctx: inventory))

        async def _must_not_run(*a, **k):  # pragma: no cover - failure signal
            raise AssertionError("agent must not run when the stage has blockers")

        monkeypatch.setattr(CurriculumAnalystHandler, "_run_agent", _must_not_run)
        result = await CurriculumAnalystHandler().execute(_ctx())
        assert result is inventory and result.topics == []

    async def test_fallback_when_nothing_parseable(self, monkeypatch):
        inventory = _outline(parseable=False)
        monkeypatch.setattr(CurriculumAnalysisHandler, "_run", staticmethod(lambda ctx: inventory))
        result = await CurriculumAnalystHandler().execute(_ctx())
        assert result is inventory

    async def test_agent_path_merges_and_records_run_id(self, monkeypatch):
        inventory = _outline()
        run_id = uuid4()
        captured = {}
        monkeypatch.setattr(CurriculumAnalysisHandler, "_run", staticmethod(lambda ctx: inventory))
        monkeypatch.setattr(
            stages,
            "_extract_parseable_texts",
            lambda ctx, outline: ([(MATERIAL_ID, "Bio Notes", "chlorophyll text")], []),
        )

        async def fake_execute_run(run_context, agent_key, user_input, **kw):
            captured["agent_key"] = agent_key
            captured["input"] = user_input
            captured["extra"] = run_context.extra
            return RunOutcome(
                run_id=run_id,
                agent_key=agent_key,
                status="completed",
                final_output=CurriculumAnalysisOutput(topics=[_topic()], summary="ok"),
            )

        import app.ai.runtime.runner as runner_module

        monkeypatch.setattr(runner_module, "execute_run", fake_execute_run)
        ctx = _ctx(rejection_notes="add more depth")
        result = await CurriculumAnalystHandler().execute(ctx)

        assert captured["agent_key"] == "curriculum_analyst"
        assert "chlorophyll text" in captured["input"]
        assert "add more depth" in captured["input"]                    # rejection feedback fed back
        assert captured["extra"]["material_ids"] == [MATERIAL_ID]      # guardrail allow-list
        assert captured["extra"]["class_id"] == str(ctx.class_id)      # Context Engine hints
        assert result.topics and result.summary == "ok"
        assert ctx.run_id == run_id                                    # ai_runs linkage


class TestRegistration:
    def test_flag_off_uses_deterministic_handler(self, monkeypatch):
        monkeypatch.setattr(ai_settings, "use_curriculum_analyst", False)
        configure_curriculum_stage()
        assert isinstance(get_handler(StageKey.CURRICULUM_ANALYSIS), CurriculumAnalysisHandler)

    def test_flag_on_uses_agent_handler(self, monkeypatch):
        monkeypatch.setattr(ai_settings, "enabled", True)
        monkeypatch.setattr(ai_settings, "use_curriculum_analyst", True)
        configure_curriculum_stage()
        try:
            assert isinstance(get_handler(StageKey.CURRICULUM_ANALYSIS), CurriculumAnalystHandler)
        finally:
            monkeypatch.setattr(ai_settings, "use_curriculum_analyst", False)
            configure_curriculum_stage()

    def test_agent_discovered_with_correct_contract(self):
        from app.ai.agents.registry import discover, get_spec

        discover(force=True)
        spec = get_spec("curriculum_analyst")
        assert spec.allowed_roles == ("teacher",)
        assert spec.structured_output == "CurriculumAnalysisOutput"
        assert "assessment" in spec.supported_workflows
        assert spec.api_invocable is False
        agent = spec.factory()  # builds a real SDK agent (tools resolved via registry)
        assert agent.output_guardrails