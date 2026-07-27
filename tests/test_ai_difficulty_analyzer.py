"""Unit tests for the Difficulty Analyzer (Phase 9): the pure deterministic
core (index, divergence, profile + notes), the guardrail's honesty rules,
the interpretation-only merge, both stage modes, and mode-driven wiring."""
from uuid import uuid4

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.ai.config import ai_settings
from app.ai.guardrails.output import validate_difficulty_analysis
from app.ai.schemas.outputs import DifficultyAnalysisOutput, DifficultyCalibration
from app.ai.schemas.runs import RunOutcome
from app.ai.workflows.assessment.domain import StageKey
from app.ai.workflows.assessment.schemas import (
    AssessmentBlueprint,
    DifficultyProfile,
    ExamComparison,
)
from app.ai.workflows.assessment.stages import (
    DifficultyAnalysisHandler,
    DifficultyAnalyzerHandler,
    HistoricalDifficulty,
    StageContext,
    as_distribution,
    build_difficulty_profile,
    configure_difficulty_stage,
    difficulty_index,
    distribution_divergence,
    get_handler,
    merge_difficulty_profile,
)


def _blueprint(difficulty_mix=None) -> AssessmentBlueprint:
    mix = {"easy": 2, "medium": 4, "hard": 4} if difficulty_mix is None else difficulty_mix
    return AssessmentBlueprint(
        total_questions=sum(mix.values()) or 10,
        difficulty_mix=mix,
        estimated_total_points=10.0,
    )


def _history(counts=None, average=None, exams=()) -> HistoricalDifficulty:
    counts = {"easy": 6, "medium": 3, "hard": 1} if counts is None else counts
    return HistoricalDifficulty(
        counts=counts, total=sum(counts.values()), exams=exams, average_percentage=average
    )


def _analysis(**overrides) -> DifficultyAnalysisOutput:
    defaults = dict(
        calibration=DifficultyCalibration.HARDER,
        assessment="This exam leans harder than usual.",
        recommendations=["Move two hard questions to medium."],
    )
    defaults.update(overrides)
    return DifficultyAnalysisOutput(**defaults)


def _ctx(**overrides) -> StageContext:
    defaults = dict(
        workflow_id=uuid4(),
        user_id=uuid4(),
        role="teacher",
        class_id=uuid4(),
        config={},
        revision=1,
        prior_artifacts={StageKey.ASSESSMENT_DESIGN.value: _blueprint().model_dump(mode="json")},
    )
    defaults.update(overrides)
    return StageContext(**defaults)


class TestPureCore:
    def test_distribution_normalizes(self):
        assert as_distribution({"easy": 1, "hard": 3}) == {"easy": 0.25, "hard": 0.75}
        assert as_distribution({}) == {}

    def test_difficulty_index_scale(self):
        assert difficulty_index({"easy": 10}) == 1.0
        assert difficulty_index({"hard": 10}) == 3.0
        assert difficulty_index({"easy": 5, "hard": 5}) == 2.0
        assert difficulty_index({}) is None

    def test_divergence_bounds(self):
        assert distribution_divergence({"easy": 1.0}, {"easy": 1.0}) == 0.0
        assert distribution_divergence({"easy": 1.0}, {"hard": 1.0}) == 1.0
        assert distribution_divergence({}, {"easy": 1.0}) is None

    def test_profile_is_complete_without_a_model(self):
        profile = build_difficulty_profile(_blueprint(), _history(average=72.0, exams=(
            ExamComparison(exam_id=str(uuid4()), title="Midterm", question_count=10),
        )))
        assert profile.mode == "deterministic"
        assert profile.target_distribution and profile.historical_distribution
        assert profile.difficulty_index == 2.2 and profile.historical_difficulty_index == 1.5
        assert profile.divergence is not None
        assert profile.exam_comparisons and profile.notes
        assert profile.calibration is None  # interpretation is the LLM mode's job

    def test_notes_flag_level_and_index_divergence(self):
        profile = build_difficulty_profile(_blueprint(), _history())
        assert any("differs notably" in n for n in profile.notes)
        assert any("harder than your recent average" in n for n in profile.notes)

    def test_notes_report_student_outcomes(self):
        profile = build_difficulty_profile(
            _blueprint(), _history(average=64.0, exams=(ExamComparison(exam_id="e", title="t", question_count=1),))
        )
        assert any("Students averaged 64%" in n for n in profile.notes)

    def test_no_history_is_stated_explicitly(self):
        profile = build_difficulty_profile(_blueprint(), HistoricalDifficulty())
        assert profile.historical_question_count == 0
        assert profile.historical_difficulty_index is None
        assert any("cannot be compared" in n for n in profile.notes)

    def test_missing_difficulty_mix_noted(self):
        profile = build_difficulty_profile(_blueprint(difficulty_mix={}), _history())
        assert any("no difficulty mix" in n for n in profile.notes)


class TestGuardrail:
    def test_valid_analysis_passes(self):
        assert validate_difficulty_analysis(_analysis(), has_history=True) == []

    def test_comparison_without_history_rejected(self):
        errors = validate_difficulty_analysis(_analysis(), has_history=False)
        assert any("no previous exams to compare against" in e for e in errors)

    def test_uncertain_is_allowed_without_history(self):
        output = _analysis(calibration=DifficultyCalibration.UNCERTAIN, recommendations=[])
        assert validate_difficulty_analysis(output, has_history=False) == []

    def test_unactionable_divergence_rejected(self):
        output = _analysis(recommendations=[])
        errors = validate_difficulty_analysis(output, has_history=True)
        assert any("no recommendation" in e for e in errors)

    def test_aligned_needs_no_recommendation(self):
        output = _analysis(calibration=DifficultyCalibration.ALIGNED, recommendations=[])
        assert validate_difficulty_analysis(output, has_history=True) == []

    def test_output_cannot_restate_the_mix(self):
        """Phase 9 constraint: the agent interprets, it does not redesign."""
        fields = set(DifficultyAnalysisOutput.model_fields)
        assert not fields & {"difficulty_mix", "target_distribution", "easy", "medium", "hard"}

    def test_calibration_vocabulary_enforced(self):
        with pytest.raises(PydanticValidationError):
            DifficultyAnalysisOutput(calibration="brutal", assessment="x")


class TestMerge:
    def test_agent_contributes_only_interpretation(self):
        profile = build_difficulty_profile(_blueprint(), _history())
        merged = merge_difficulty_profile(profile, _analysis())
        assert merged.mode == "llm"
        assert merged.calibration == "harder"
        assert merged.assessment and merged.recommendations
        # every computed number is untouched
        assert merged.target_distribution == profile.target_distribution
        assert merged.historical_distribution == profile.historical_distribution
        assert merged.difficulty_index == profile.difficulty_index
        assert merged.divergence == profile.divergence
        assert merged.notes == profile.notes


class TestHandlers:
    async def test_deterministic_mode_never_calls_a_model(self, monkeypatch):
        import app.ai.workflows.assessment.stages as stages_module
        import app.ai.runtime.runner as runner_module

        monkeypatch.setattr(
            stages_module, "load_historical_difficulty", lambda user_id, **kw: _history()
        )

        async def _must_not_run(*a, **k):  # pragma: no cover - failure signal
            raise AssertionError("deterministic mode must not invoke an agent")

        monkeypatch.setattr(runner_module, "execute_run", _must_not_run)
        profile = await DifficultyAnalysisHandler().execute(_ctx())
        assert profile.mode == "deterministic" and profile.calibration is None

    async def test_llm_mode_merges_and_records_run_id(self, monkeypatch):
        import app.ai.workflows.assessment.stages as stages_module
        import app.ai.runtime.runner as runner_module

        run_id = uuid4()
        captured = {}
        monkeypatch.setattr(
            stages_module,
            "load_historical_difficulty",
            lambda user_id, **kw: _history(
                exams=(ExamComparison(exam_id="e1", title="Midterm", question_count=10),)
            ),
        )

        async def fake_execute_run(run_context, agent_key, user_input, **kw):
            captured["agent_key"] = agent_key
            captured["input"] = user_input
            captured["extra"] = run_context.extra
            return RunOutcome(
                run_id=run_id, agent_key=agent_key, status="completed", final_output=_analysis()
            )

        monkeypatch.setattr(runner_module, "execute_run", fake_execute_run)
        ctx = _ctx(rejection_notes="explain the jump in difficulty")
        result = await DifficultyAnalyzerHandler().execute(ctx)

        assert captured["agent_key"] == "difficulty_analyzer"
        assert "difficulty_index" in captured["input"]                 # computed stats fed in
        assert "Midterm" in captured["input"]                          # previous exams fed in
        assert "explain the jump in difficulty" in captured["input"]   # rejection feedback
        assert captured["extra"]["has_history"] is True                # guardrail input
        assert result.mode == "llm" and result.calibration == "harder"
        assert ctx.run_id == run_id                                    # ai_runs linkage

    async def test_llm_mode_skips_agent_without_a_difficulty_mix(self, monkeypatch):
        import app.ai.workflows.assessment.stages as stages_module
        import app.ai.runtime.runner as runner_module

        monkeypatch.setattr(
            stages_module, "load_historical_difficulty", lambda user_id, **kw: _history()
        )

        async def _must_not_run(*a, **k):  # pragma: no cover - failure signal
            raise AssertionError("nothing to interpret without a difficulty mix")

        monkeypatch.setattr(runner_module, "execute_run", _must_not_run)
        ctx = _ctx(
            prior_artifacts={
                StageKey.ASSESSMENT_DESIGN.value: _blueprint(difficulty_mix={}).model_dump(mode="json")
            }
        )
        profile = await DifficultyAnalyzerHandler().execute(ctx)
        assert profile.mode == "deterministic"

    async def test_llm_mode_flags_absent_history_to_the_agent(self, monkeypatch):
        import app.ai.workflows.assessment.stages as stages_module
        import app.ai.runtime.runner as runner_module

        monkeypatch.setattr(
            stages_module, "load_historical_difficulty", lambda user_id, **kw: HistoricalDifficulty()
        )

        async def fake_execute_run(run_context, agent_key, user_input, **kw):
            assert "must be 'uncertain'" in user_input
            assert run_context.extra["has_history"] is False
            return RunOutcome(
                run_id=uuid4(),
                agent_key=agent_key,
                status="completed",
                final_output=_analysis(
                    calibration=DifficultyCalibration.UNCERTAIN, recommendations=[]
                ),
            )

        monkeypatch.setattr(runner_module, "execute_run", fake_execute_run)
        result = await DifficultyAnalyzerHandler().execute(_ctx())
        assert result.calibration == "uncertain"


class TestModeWiring:
    def test_default_mode_is_deterministic(self, monkeypatch):
        monkeypatch.setattr(ai_settings, "difficulty_analysis_mode", "deterministic")
        configure_difficulty_stage()
        assert isinstance(get_handler(StageKey.DIFFICULTY_ANALYSIS), DifficultyAnalysisHandler)

    def test_llm_mode_selects_the_agent_handler(self, monkeypatch):
        monkeypatch.setattr(ai_settings, "enabled", True)
        monkeypatch.setattr(ai_settings, "difficulty_analysis_mode", "LLM")  # case-insensitive
        configure_difficulty_stage()
        try:
            assert isinstance(get_handler(StageKey.DIFFICULTY_ANALYSIS), DifficultyAnalyzerHandler)
        finally:
            monkeypatch.setattr(ai_settings, "difficulty_analysis_mode", "deterministic")
            configure_difficulty_stage()

    def test_unknown_mode_falls_back_to_deterministic(self, monkeypatch):
        monkeypatch.setattr(ai_settings, "enabled", True)
        monkeypatch.setattr(ai_settings, "difficulty_analysis_mode", "magic")
        configure_difficulty_stage()
        try:
            assert isinstance(get_handler(StageKey.DIFFICULTY_ANALYSIS), DifficultyAnalysisHandler)
        finally:
            monkeypatch.setattr(ai_settings, "difficulty_analysis_mode", "deterministic")
            configure_difficulty_stage()

    def test_agent_contract_and_no_database_reach(self):
        from app.ai.agents.registry import discover, get_spec

        discover(force=True)
        spec = get_spec("difficulty_analyzer")
        assert spec.allowed_roles == ("teacher",)
        assert spec.structured_output == "DifficultyAnalysisOutput"
        assert "assessment" in spec.supported_workflows
        assert spec.api_invocable is False
        assert spec.required_tools == ()      # no tools -> no database access
        agent = spec.factory()
        assert agent.tools == [] and agent.output_guardrails
