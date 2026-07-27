"""Unit tests for the Scheduler (Phase 10): duration estimation, timezone-safe
constraint analysis, calendar-conflict findings, the guardrail's honesty
rules, the advice-only merge, both handlers, and the phase's hard constraint
— nothing in this stage can publish an exam."""
import ast
import inspect
import textwrap
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.ai.config import ai_settings
from app.ai.guardrails.output import validate_schedule_plan
from app.ai.schemas.outputs import ScheduleReadiness, SchedulePlanOutput
from app.ai.schemas.runs import RunOutcome
from app.ai.workflows.assessment.domain import StageKey
from app.ai.workflows.assessment.schemas import (
    AssessmentBlueprint,
    ScheduleConflict,
    SchedulePlan,
)
from app.ai.workflows.assessment.stages import (
    SchedulerHandler,
    SchedulingHandler,
    StageContext,
    _as_aware_utc,
    configure_scheduling_stage,
    estimate_exam_duration,
    get_handler,
    merge_schedule_plan,
    plan_schedule,
)

START = "2026-08-01T10:00:00"
END = "2026-08-01T12:00:00"


def _blueprint(type_mix=None, total=10) -> AssessmentBlueprint:
    return AssessmentBlueprint(
        total_questions=total,
        type_mix={"mcq": 10} if type_mix is None else type_mix,
        estimated_total_points=float(total),
    )


def _config(**overrides) -> dict:
    defaults = {"duration_minutes": 60, "proposed_start": START, "proposed_end": END}
    defaults.update(overrides)
    return defaults


def _advice(**overrides) -> SchedulePlanOutput:
    defaults = dict(
        readiness=ScheduleReadiness.ADJUST,
        rationale="The window is tight for this question mix.",
        recommendations=["Extend the window by 30 minutes."],
    )
    defaults.update(overrides)
    return SchedulePlanOutput(**defaults)


def _ctx(**overrides) -> StageContext:
    defaults = dict(
        workflow_id=uuid4(),
        user_id=uuid4(),
        role="teacher",
        class_id=uuid4(),
        config=_config(),
        revision=1,
        prior_artifacts={StageKey.ASSESSMENT_DESIGN.value: _blueprint().model_dump(mode="json")},
    )
    defaults.update(overrides)
    return StageContext(**defaults)


class TestDurationEstimation:
    def test_estimates_from_type_mix(self):
        minutes, basis = estimate_exam_duration(
            _blueprint(type_mix={"mcq": 10, "long_answer": 2})
        )
        assert minutes == 35  # 10 * 1.5 + 2 * 10
        assert basis["mcq"] == 1.5 and basis["long_answer"] == 10.0

    def test_falls_back_to_total_questions(self):
        minutes, basis = estimate_exam_duration(_blueprint(type_mix={}, total=8))
        assert minutes == 16 and basis == {"default": 2.0}

    def test_no_blueprint_gives_no_estimate(self):
        assert estimate_exam_duration(None) == (None, {})


class TestTimezoneSafety:
    def test_naive_values_are_treated_as_utc(self):
        parsed = _as_aware_utc(START)
        assert parsed.tzinfo is not None and parsed.utcoffset() == timedelta(0)

    def test_aware_values_are_normalized(self):
        aware = datetime(2026, 8, 1, 15, 0, tzinfo=timezone(timedelta(hours=5)))
        assert _as_aware_utc(aware).hour == 10

    def test_garbage_is_ignored_not_raised(self):
        assert _as_aware_utc("not-a-date") is None
        assert _as_aware_utc(None) is None

    def test_window_math_mixes_naive_and_aware_safely(self):
        aware_end = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
        plan = plan_schedule({"proposed_start": START, "proposed_end": aware_end, "duration_minutes": 30})
        assert plan.window_minutes == 120.0


class TestConstraintAnalysis:
    def test_blocker_on_inverted_window(self):
        plan = plan_schedule(_config(proposed_end="2026-08-01T09:00:00"))
        assert any(f.severity == "blocker" for f in plan.findings)

    def test_blocker_when_duration_exceeds_window(self):
        plan = plan_schedule(_config(duration_minutes=180))
        assert any("exceeds the exam window" in f.message for f in plan.findings)

    def test_warning_without_duration(self):
        plan = plan_schedule(_config(duration_minutes=None))
        assert any("No duration set" in f.message for f in plan.findings)

    def test_warning_without_window(self):
        plan = plan_schedule({"duration_minutes": 60})
        assert any("No exam window proposed" in f.message for f in plan.findings)

    def test_warning_when_duration_below_estimate(self):
        plan = plan_schedule(
            _config(duration_minutes=10), _blueprint(type_mix={"long_answer": 5})
        )
        assert any("may be tight" in f.message for f in plan.findings)
        assert plan.estimated_duration_minutes == 50

    def test_estimate_offered_when_duration_absent(self):
        plan = plan_schedule(_config(duration_minutes=None), _blueprint())
        assert any("suggests about" in f.message for f in plan.findings)

    def test_window_length_recorded(self):
        assert plan_schedule(_config()).window_minutes == 120.0


class TestCalendarConflicts:
    def test_conflicts_become_findings(self):
        conflict = ScheduleConflict(
            exam_id=str(uuid4()), title="Physics Midterm", overlap_minutes=45.0
        )
        plan = plan_schedule(_config(), _blueprint(), (conflict,))
        assert plan.conflicts and plan.conflicts[0].title == "Physics Midterm"
        assert any("Overlaps 'Physics Midterm'" in f.message for f in plan.findings)
        assert any("45 min overlap" in f.message for f in plan.findings)

    def test_no_conflicts_is_clean(self):
        plan = plan_schedule(_config(), _blueprint())
        assert plan.conflicts == []
        assert not any("Overlaps" in f.message for f in plan.findings)


class TestGuardrail:
    def test_valid_advice_passes(self):
        assert validate_schedule_plan(_advice(), has_window=True) == []

    def test_verdict_without_window_rejected(self):
        errors = validate_schedule_plan(_advice(), has_window=False)
        assert any("no exam window was proposed" in e for e in errors)

    def test_insufficient_information_allowed_without_window(self):
        output = _advice(
            readiness=ScheduleReadiness.INSUFFICIENT_INFORMATION, recommendations=[]
        )
        assert validate_schedule_plan(output, has_window=False) == []

    def test_insufficient_information_contradicting_window_rejected(self):
        output = _advice(readiness=ScheduleReadiness.INSUFFICIENT_INFORMATION)
        errors = validate_schedule_plan(output, has_window=True)
        assert any("contradicts the proposed exam window" in e for e in errors)

    def test_unactionable_verdict_rejected(self):
        errors = validate_schedule_plan(_advice(recommendations=[]), has_window=True)
        assert any("no recommendation" in e for e in errors)

    def test_ready_needs_no_recommendation(self):
        output = _advice(readiness=ScheduleReadiness.READY, recommendations=[])
        assert validate_schedule_plan(output, has_window=True) == []

    def test_suggested_duration_must_be_sane(self):
        with pytest.raises(PydanticValidationError):
            _advice(recommended_duration_minutes=0)
        with pytest.raises(PydanticValidationError):
            _advice(recommended_duration_minutes=10_000)


class TestNoPublishing:
    """Phase 10's hard constraint, checked structurally."""

    def test_output_has_no_publishing_field(self):
        fields = set(SchedulePlanOutput.model_fields)
        assert not fields & {"publish", "is_published", "publish_exam", "approved"}

    def test_agent_has_no_tools_so_cannot_reach_publish(self):
        from app.ai.agents.registry import discover, get_spec

        discover(force=True)
        spec = get_spec("scheduler")
        assert spec.required_tools == ()
        assert spec.factory().tools == []

    def test_scheduling_stage_never_calls_publish(self):
        """No identifier related to publishing is referenced anywhere in the
        scheduling path (AST-based, so prose in docstrings doesn't count)."""
        for func in (plan_schedule, SchedulingHandler.execute, SchedulerHandler.execute,
                     SchedulerHandler._run_agent, merge_schedule_plan):
            tree = ast.parse(textwrap.dedent(inspect.getsource(func)))
            referenced = {
                node.attr if isinstance(node, ast.Attribute) else node.id
                for node in ast.walk(tree)
                if isinstance(node, (ast.Attribute, ast.Name))
            }
            offending = [name for name in referenced if "publish" in name.lower()]
            assert not offending, f"{func.__qualname__} references {offending}"

    def test_merge_never_applies_the_suggested_duration(self):
        plan = plan_schedule(_config(duration_minutes=60), _blueprint())
        merged = merge_schedule_plan(plan, _advice(recommended_duration_minutes=90))
        assert merged.duration_minutes == 60                      # teacher's value untouched
        assert merged.recommended_duration_minutes == 90          # suggestion recorded separately


class TestMerge:
    def test_agent_contributes_only_advice(self):
        plan = plan_schedule(_config(), _blueprint(), (
            ScheduleConflict(exam_id="e", title="Other", overlap_minutes=10.0),
        ))
        merged = merge_schedule_plan(plan, _advice())
        assert merged.readiness == "adjust" and merged.rationale and merged.recommendations
        # everything deterministic is preserved
        assert merged.proposed_start == plan.proposed_start
        assert merged.proposed_end == plan.proposed_end
        assert merged.window_minutes == plan.window_minutes
        assert merged.estimated_duration_minutes == plan.estimated_duration_minutes
        assert merged.conflicts == plan.conflicts
        assert merged.findings == plan.findings


class TestHandlers:
    async def test_deterministic_handler_never_calls_a_model(self, monkeypatch):
        import app.ai.runtime.runner as runner_module
        import app.ai.workflows.assessment.stages as stages_module

        monkeypatch.setattr(
            stages_module, "_schedule_inputs", lambda ctx: (_blueprint(), ())
        )

        async def _must_not_run(*a, **k):  # pragma: no cover - failure signal
            raise AssertionError("deterministic handler must not invoke an agent")

        monkeypatch.setattr(runner_module, "execute_run", _must_not_run)
        plan = await SchedulingHandler().execute(_ctx())
        assert plan.readiness is None and plan.estimated_duration_minutes == 15

    async def test_agent_path_merges_and_records_run_id(self, monkeypatch):
        import app.ai.runtime.runner as runner_module
        import app.ai.workflows.assessment.stages as stages_module

        run_id = uuid4()
        captured = {}
        monkeypatch.setattr(
            stages_module,
            "_schedule_inputs",
            lambda ctx: (
                _blueprint(),
                (ScheduleConflict(exam_id="e1", title="Physics Midterm", overlap_minutes=30.0),),
            ),
        )

        async def fake_execute_run(run_context, agent_key, user_input, **kw):
            captured["agent_key"] = agent_key
            captured["input"] = user_input
            captured["extra"] = run_context.extra
            return RunOutcome(
                run_id=run_id, agent_key=agent_key, status="completed", final_output=_advice()
            )

        monkeypatch.setattr(runner_module, "execute_run", fake_execute_run)
        ctx = _ctx(rejection_notes="avoid clashing with the physics paper")
        result = await SchedulerHandler().execute(ctx)

        assert captured["agent_key"] == "scheduler"
        assert "estimated_duration_minutes" in captured["input"]        # duration analysis fed in
        assert "Physics Midterm" in captured["input"]                   # calendar fed in
        assert "avoid clashing" in captured["input"]                    # rejection feedback
        assert captured["extra"]["has_window"] is True                  # guardrail input
        assert result.readiness == "adjust"
        assert ctx.run_id == run_id                                     # ai_runs linkage

    async def test_agent_skipped_without_a_window(self, monkeypatch):
        import app.ai.runtime.runner as runner_module
        import app.ai.workflows.assessment.stages as stages_module

        monkeypatch.setattr(stages_module, "_schedule_inputs", lambda ctx: (_blueprint(), ()))

        async def _must_not_run(*a, **k):  # pragma: no cover - failure signal
            raise AssertionError("nothing to assess without a window")

        monkeypatch.setattr(runner_module, "execute_run", _must_not_run)
        plan = await SchedulerHandler().execute(
            _ctx(config={"duration_minutes": 60})
        )
        assert plan.readiness is None
        assert any("No exam window proposed" in f.message for f in plan.findings)


class TestRegistration:
    def test_flag_off_uses_deterministic_handler(self, monkeypatch):
        monkeypatch.setattr(ai_settings, "use_scheduler", False)
        configure_scheduling_stage()
        assert isinstance(get_handler(StageKey.SCHEDULING), SchedulingHandler)

    def test_flag_on_uses_agent_handler(self, monkeypatch):
        monkeypatch.setattr(ai_settings, "enabled", True)
        monkeypatch.setattr(ai_settings, "use_scheduler", True)
        configure_scheduling_stage()
        try:
            assert isinstance(get_handler(StageKey.SCHEDULING), SchedulerHandler)
        finally:
            monkeypatch.setattr(ai_settings, "use_scheduler", False)
            configure_scheduling_stage()

    def test_agent_contract(self):
        from app.ai.agents.registry import discover, get_spec

        discover(force=True)
        spec = get_spec("scheduler")
        assert spec.allowed_roles == ("teacher",)
        assert spec.structured_output == "SchedulePlanOutput"
        assert "assessment" in spec.supported_workflows
        assert spec.api_invocable is False
        assert spec.factory().output_guardrails
