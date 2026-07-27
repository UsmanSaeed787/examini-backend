"""Regression guard for the PRE-EXISTING exam paths.

The assessment workspace shares three things with the older "Generate with AI"
form and the manual create form: the `exam_generator` agent's output schema, the
`ExamCreate` projection, and `ParserService`. Changes made for the workspace
must not alter how those older paths behave — these tests pin the parts that
could drift silently.
"""
import pytest

from app.ai.facade import _to_exam_create
from app.ai.guardrails.output import validate_generated_exam
from app.ai.schemas.outputs import GeneratedExamOutput, GeneratedOption, GeneratedQuestion
from app.schemas.exam import ExamCreate, ExamGenerate
from app.utils.constants import DifficultyLevel, QuestionType
from uuid import uuid4


def _exam_generate(**overrides) -> ExamGenerate:
    defaults = dict(
        title="Legacy Quiz",
        description="from the old form",
        class_id=uuid4(),
        material_ids=[uuid4()],
        question_config={"total": 2, "mcq": 1, "short_answer": 1},
        duration_minutes=30,
    )
    defaults.update(overrides)
    return ExamGenerate(**defaults)


def _output(topic=None) -> GeneratedExamOutput:
    return GeneratedExamOutput(
        questions=[
            GeneratedQuestion(
                question_text="Which organelle makes ATP?",
                question_type=QuestionType.MCQ,
                difficulty_level=DifficultyLevel.EASY,
                points=2.0,
                order_number=1,
                topic=topic,
                options=[
                    GeneratedOption(option_text="Mitochondrion", is_correct=True, order_number=1),
                    GeneratedOption(option_text="Ribosome", is_correct=False, order_number=2),
                ],
            ),
            GeneratedQuestion(
                question_text="Explain osmosis.",
                question_type=QuestionType.SHORT_ANSWER,
                difficulty_level=DifficultyLevel.MEDIUM,
                topic=topic,
            ),
        ]
    )


class TestGeneratedQuestionSchemaStaysBackwardCompatible:
    """`topic` was added for the workspace's blueprint verification. The older
    path never sends or reads it, so it must remain optional."""

    def test_topic_is_optional(self):
        q = GeneratedQuestion(question_text="Q", question_type=QuestionType.SHORT_ANSWER)
        assert q.topic is None

    def test_output_without_topics_still_validates(self):
        assert len(_output().questions) == 2


class TestFacadeProjection:
    """`_to_exam_create` is what the old form's agent branch persists through."""

    def test_maps_questions_and_options(self):
        exam = _to_exam_create(_exam_generate(), _output())
        assert isinstance(exam, ExamCreate)
        assert exam.title == "Legacy Quiz"
        assert exam.duration_minutes == 30
        assert len(exam.questions) == 2
        assert exam.questions[0].options is not None
        assert len(exam.questions[0].options) == 2
        assert exam.questions[1].options is None  # short answer takes none

    def test_topic_is_not_persisted(self):
        """The exam schema has no topic column; a tagged question must map the
        same as an untagged one."""
        tagged = _to_exam_create(_exam_generate(), _output(topic="Cell Biology"))
        untagged = _to_exam_create(_exam_generate(), _output())
        assert tagged.questions[0].model_dump() == untagged.questions[0].model_dump()

    def test_order_numbers_backfilled(self):
        output = _output()
        for q in output.questions:
            q.order_number = None
        exam = _to_exam_create(_exam_generate(), output)
        assert [q.order_number for q in exam.questions] == [1, 2]

    def test_produces_an_unpublished_draft(self):
        """Both the old and new paths create drafts — ExamCreate cannot express
        anything else."""
        assert not set(ExamCreate.model_fields) & {"is_published", "publish"}

    def test_carries_the_teachers_schedule_verbatim(self):
        from datetime import datetime, timezone

        start = datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc)
        exam = _to_exam_create(
            _exam_generate(start_date=start, allow_retake=True, max_attempts=3), _output()
        )
        assert exam.start_date == start
        assert exam.allow_retake is True
        assert exam.max_attempts == 3


class TestLegacyGuardrailUnchanged:
    """The old form validates against a raw question_config, not a blueprint."""

    def test_matching_config_passes(self):
        config = {"total": 2, "mcq": 1, "short_answer": 1, "easy": 1, "medium": 1}
        assert validate_generated_exam(_output(), config) == []

    def test_count_mismatch_still_reported(self):
        errors = validate_generated_exam(_output(), {"total": 5})
        assert any("Expected 5 questions" in e for e in errors)

    def test_topic_tagging_does_not_affect_the_legacy_check(self):
        config = {"total": 2, "mcq": 1, "short_answer": 1}
        assert validate_generated_exam(_output(topic="Anything"), config) == validate_generated_exam(
            _output(), config
        )


class TestParserChangeIsConsistentAcrossPaths:
    """The scanned-PDF fix lives in ParserService, which all three generation
    paths share — workspace, facade, and the legacy OpenAIService branch."""

    def test_legacy_branch_uses_the_same_parser(self):
        import inspect

        from app.services.openai_service import OpenAIService

        source = inspect.getsource(OpenAIService.parse_material_file)
        assert "ParserService.extract_text" in source

    def test_real_prose_is_still_accepted(self):
        from app.services.parser_service import MIN_EXTRACTED_CHARS, distinct_text_length

        prose = (
            "The mitochondrion is the site of aerobic respiration.\n"
            "Chloroplasts carry out photosynthesis in plant cells.\n"
            "Ribosomes translate messenger RNA into proteins.\n"
        )
        assert distinct_text_length(prose) > MIN_EXTRACTED_CHARS
