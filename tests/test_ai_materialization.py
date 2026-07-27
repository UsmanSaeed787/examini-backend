"""Unit tests for assessment materialization (Phase 11): the approved plan
becoming a real exam.

Covers the gating rules, the blueprint projection, post-generation quality
validation, the deterministic exam mapping, and the phase's hard constraint —
generation can never publish, and publishing is reachable only from an
explicit human request.
"""
import ast
import inspect
import textwrap
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.ai.guardrails.output import (
    blueprint_question_config,
    validate_generated_against_blueprint,
)
from app.ai.schemas.outputs import (
    GeneratedExamOutput,
    GeneratedOption,
    GeneratedQuestion,
    TopicAllocation,
)
from app.ai.workflows.assessment import materialization
from app.ai.workflows.assessment.domain import GenerationStatus
from app.ai.workflows.assessment.materialization import (
    build_generation_input,
    plan_blockers,
    resolve_duration,
    to_exam_create,
)
from app.ai.workflows.assessment.schemas import (
    AssessmentBlueprint,
    AssessmentPlan,
    CurriculumOutline,
    CurriculumUnit,
    DifficultyProfile,
    Finding,
    QualityReport,
    SchedulePlan,
)
from app.ai.workflows.assessment.state_machine import ensure_generation_transition
from app.middleware.error_handler import ValidationError
from app.utils.constants import DifficultyLevel, QuestionType

START = datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc)


def _blueprint(**overrides) -> AssessmentBlueprint:
    defaults = dict(
        total_questions=4,
        type_mix={"mcq": 2, "short_answer": 2},
        difficulty_mix={"easy": 2, "medium": 2},
        default_points=1.0,
        estimated_total_points=4.0,
    )
    defaults.update(overrides)
    return AssessmentBlueprint(**defaults)


def _outline(**overrides) -> CurriculumOutline:
    defaults = dict(
        class_id=str(uuid4()),
        class_name="Physics 101",
        units=[
            CurriculumUnit(material_id=str(uuid4()), title="Kinematics", file_type="pdf", parseable=True)
        ],
    )
    defaults.update(overrides)
    return CurriculumOutline(**defaults)


def _plan(**overrides) -> AssessmentPlan:
    outline = overrides.pop("outline", _outline())
    defaults = dict(
        workflow_id=str(uuid4()),
        title="Midterm",
        class_id=outline.class_id,
        outline=outline,
        blueprint=_blueprint(),
        quality=QualityReport(passed=True),
        difficulty=DifficultyProfile(),
        schedule=SchedulePlan(duration_minutes=60, proposed_start=START, proposed_end=START + timedelta(hours=2)),
        approved_at=START,
    )
    defaults.update(overrides)
    return AssessmentPlan(**defaults)


def _questions(count=4, topic=None) -> list[GeneratedQuestion]:
    out = []
    for i in range(count):
        is_mcq = i < 2
        out.append(
            GeneratedQuestion(
                question_text=f"Q{i + 1}?",
                question_type=QuestionType.MCQ if is_mcq else QuestionType.SHORT_ANSWER,
                difficulty_level=DifficultyLevel.EASY if is_mcq else DifficultyLevel.MEDIUM,
                order_number=i + 1,
                topic=topic,
                options=[
                    GeneratedOption(option_text="a", is_correct=True, order_number=1),
                    GeneratedOption(option_text="b", is_correct=False, order_number=2),
                ]
                if is_mcq
                else None,
            )
        )
    return out


class TestGenerationStateMachine:
    def test_legal_path(self):
        ensure_generation_transition(GenerationStatus.PENDING, GenerationStatus.GENERATING)
        ensure_generation_transition(GenerationStatus.GENERATING, GenerationStatus.GENERATED)
        ensure_generation_transition(GenerationStatus.GENERATED, GenerationStatus.PUBLISHED)

    def test_publish_only_reachable_from_generated(self):
        for origin in (
            GenerationStatus.PENDING,
            GenerationStatus.GENERATING,
            GenerationStatus.FAILED,
            GenerationStatus.SUPERSEDED,
        ):
            with pytest.raises(ValidationError):
                ensure_generation_transition(origin, GenerationStatus.PUBLISHED)

    def test_published_is_terminal(self):
        for target in GenerationStatus:
            with pytest.raises(ValidationError):
                ensure_generation_transition(GenerationStatus.PUBLISHED, target)

    def test_failed_attempt_can_be_superseded_but_not_resumed(self):
        ensure_generation_transition(GenerationStatus.FAILED, GenerationStatus.SUPERSEDED)
        with pytest.raises(ValidationError):
            ensure_generation_transition(GenerationStatus.FAILED, GenerationStatus.GENERATED)


class TestPlanGating:
    def test_clean_plan_has_no_blockers(self):
        assert plan_blockers(_plan()) == []

    def test_failed_quality_review_blocks(self):
        blockers = plan_blockers(_plan(quality=QualityReport(passed=False)))
        assert any("quality review did not pass" in b for b in blockers)

    def test_standing_quality_blocker_blocks_even_when_passed(self):
        quality = QualityReport(
            passed=True,
            findings=[Finding(severity="blocker", message="No parseable material", stage="quality_review")],
        )
        assert any("Unresolved quality blocker" in b for b in plan_blockers(_plan(quality=quality)))

    def test_blocked_schedule_readiness_blocks(self):
        schedule = SchedulePlan(duration_minutes=60, readiness="blocked")
        assert any("blocked" in b for b in plan_blockers(_plan(schedule=schedule)))

    def test_empty_blueprint_blocks(self):
        blueprint = _blueprint(total_questions=0, type_mix={}, difficulty_mix={}, estimated_total_points=0.0)
        assert any("no questions" in b for b in plan_blockers(_plan(blueprint=blueprint)))

    def test_blueprint_validation_errors_block(self):
        blueprint = _blueprint(validation_errors=["type counts must sum to total"])
        assert any("validation errors" in b for b in plan_blockers(_plan(blueprint=blueprint)))


class TestDurationResolution:
    def test_teacher_duration_wins(self):
        plan = _plan(schedule=SchedulePlan(duration_minutes=90, estimated_duration_minutes=45))
        assert resolve_duration(plan) == 90

    def test_falls_back_to_estimate(self):
        plan = _plan(schedule=SchedulePlan(estimated_duration_minutes=45))
        assert resolve_duration(plan) == 45

    def test_agent_recommendation_is_never_applied(self):
        """recommended_duration_minutes is advisory only — it must not become
        the exam's duration (mirrors merge_schedule_plan upstream)."""
        plan = _plan(schedule=SchedulePlan(recommended_duration_minutes=120))
        with pytest.raises(ValidationError):
            resolve_duration(plan)

    def test_missing_duration_raises(self):
        with pytest.raises(ValidationError):
            resolve_duration(_plan(schedule=SchedulePlan()))


class TestBlueprintProjection:
    def test_config_carries_total_and_both_mixes(self):
        config = blueprint_question_config(_blueprint())
        assert config == {"total": 4, "mcq": 2, "short_answer": 2, "easy": 2, "medium": 2}

    def test_generation_follows_the_approved_blueprint_not_the_request(self):
        """After a rejection + config_patch the blueprint is the source of
        truth; the projection must reflect the approved counts."""
        config = blueprint_question_config(_blueprint(total_questions=6, type_mix={"mcq": 6}))
        assert config["total"] == 6 and config["mcq"] == 6


class TestPostGenerationValidation:
    def test_matching_output_is_clean(self):
        assert validate_generated_against_blueprint(
            GeneratedExamOutput(questions=_questions()), _blueprint()
        ) == []

    def test_count_mismatch_is_reported(self):
        errors = validate_generated_against_blueprint(
            GeneratedExamOutput(questions=_questions(count=2)), _blueprint()
        )
        assert any("Expected 4 questions" in e for e in errors)

    def test_topic_allocation_shortfall_is_reported(self):
        blueprint = _blueprint(
            topic_allocations=[
                TopicAllocation(topic_title="Kinematics", question_count=3),
                TopicAllocation(topic_title="Dynamics", question_count=1),
            ]
        )
        output = GeneratedExamOutput(questions=_questions(topic="Kinematics"))
        errors = validate_generated_against_blueprint(output, blueprint)
        assert any("'Kinematics': blueprint allocates 3" in e for e in errors)
        assert any("'Dynamics': blueprint allocates 1" in e for e in errors)

    def test_invented_topic_is_reported(self):
        blueprint = _blueprint(
            topic_allocations=[TopicAllocation(topic_title="Kinematics", question_count=4)]
        )
        output = GeneratedExamOutput(questions=_questions(topic="Astrology"))
        errors = validate_generated_against_blueprint(output, blueprint)
        assert any("outside the blueprint" in e for e in errors)

    def test_untagged_questions_skip_topic_checks_rather_than_passing_them(self):
        """An unverifiable dimension is reported as nothing, never as a pass."""
        blueprint = _blueprint(
            topic_allocations=[TopicAllocation(topic_title="Kinematics", question_count=4)]
        )
        assert validate_generated_against_blueprint(
            GeneratedExamOutput(questions=_questions()), blueprint
        ) == []


class TestExamMapping:
    def test_maps_questions_options_and_window(self):
        plan = _plan()
        exam = to_exam_create(plan, "Midterm", 60, GeneratedExamOutput(questions=_questions()))
        assert exam.title == "Midterm"
        assert exam.duration_minutes == 60
        assert len(exam.questions) == 4
        assert exam.start_date == START
        assert exam.questions[0].options is not None and len(exam.questions[0].options) == 2
        assert exam.questions[2].options is None  # short answer takes no options

    def test_order_numbers_are_backfilled(self):
        questions = _questions()
        for q in questions:
            q.order_number = None
        exam = to_exam_create(_plan(), "T", 60, GeneratedExamOutput(questions=questions))
        assert [q.order_number for q in exam.questions] == [1, 2, 3, 4]

    def test_topic_is_a_verification_signal_and_is_not_persisted(self):
        exam = to_exam_create(
            _plan(), "T", 60, GeneratedExamOutput(questions=_questions(topic="Kinematics"))
        )
        assert not hasattr(exam.questions[0], "topic")

    def test_created_exam_cannot_carry_a_published_flag(self):
        """ExamCreate has no publish field, so the generated exam is always a
        draft — is_published defaults to False on the model."""
        from app.schemas.exam import ExamCreate

        assert not set(ExamCreate.model_fields) & {"is_published", "publish", "published"}


class TestGenerationInput:
    def test_material_text_is_delimited_as_data(self):
        text = build_generation_input(_plan(), [("Kinematics", "v = u + at")])
        assert "=== Material: Kinematics ===" in text
        assert "v = u + at" in text

    def test_allocations_are_passed_as_binding_when_present(self):
        plan = _plan(
            blueprint=_blueprint(
                topic_allocations=[TopicAllocation(topic_title="Kinematics", question_count=4)]
            )
        )
        assert "Topic allocation plan" in build_generation_input(plan, [])

    def test_no_allocation_section_when_the_design_has_none(self):
        assert "Topic allocation plan" not in build_generation_input(_plan(), [])


class TestPublishingIsHumanOnly:
    """The phase's hard constraint, mirroring the Scheduler's no-publish rule:
    generation produces a draft, and only an explicit teacher request can make
    an exam visible to students."""

    def test_only_publish_sync_touches_publish_exam(self):
        """AST-based, module-wide: exactly one function in the materialization
        module may reference ExamService.publish_exam."""
        tree = ast.parse(inspect.getsource(materialization))
        offenders = set()
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            names = {
                child.attr if isinstance(child, ast.Attribute) else child.id
                for child in ast.walk(node)
                if isinstance(child, (ast.Attribute, ast.Name))
            }
            if "publish_exam" in names:
                offenders.add(node.name)
        assert offenders == {"_publish_sync"}

    def test_generation_path_references_nothing_publish_related(self):
        for func in (build_generation_input, to_exam_create, materialization.generate_assessment):
            tree = ast.parse(textwrap.dedent(inspect.getsource(func)))
            referenced = {
                node.attr if isinstance(node, ast.Attribute) else node.id
                for node in ast.walk(tree)
                if isinstance(node, (ast.Attribute, ast.Name))
            }
            offending = [n for n in referenced if "publish" in n.lower()]
            assert not offending, f"{func.__qualname__} references {offending}"

    def test_generator_output_has_no_publishing_field(self):
        assert not set(GeneratedQuestion.model_fields) & {"publish", "is_published", "published"}
        assert not set(GeneratedExamOutput.model_fields) & {"publish", "is_published", "published"}

    def test_no_role_has_a_publishing_capability(self):
        from app.ai.policies.authz import TOOL_CAPABILITIES

        for role, tools in TOOL_CAPABILITIES.items():
            offending = [t for t in tools if "publish" in t.lower()]
            assert not offending, f"role '{role}' is granted {offending}"

    def test_exam_generator_agent_has_no_publish_tool(self):
        from app.ai.agents.exam_generator import DEFINITION

        assert not [t for t in DEFINITION.required_tools if "publish" in t.lower()]
