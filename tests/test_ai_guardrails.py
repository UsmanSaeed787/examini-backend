"""Unit tests for the AI layer's pure guardrail validators (SDK-free)."""
from app.ai.guardrails.input import validate_material_selection, validate_question_config
from app.ai.guardrails.output import validate_generated_exam
from app.ai.schemas.outputs import GeneratedExamOutput, GeneratedOption, GeneratedQuestion
from app.utils.constants import DifficultyLevel, QuestionType


def _mcq(text="Q", correct=1, options=3, difficulty=DifficultyLevel.MEDIUM):
    return GeneratedQuestion(
        question_text=text,
        question_type=QuestionType.MCQ,
        difficulty_level=difficulty,
        options=[
            GeneratedOption(option_text=f"opt{i}", is_correct=i < correct) for i in range(options)
        ],
    )


class TestQuestionConfigValidation:
    def test_valid_config_passes(self):
        assert validate_question_config({"total": 10, "easy": 3, "medium": 4, "hard": 3}) == []

    def test_empty_config_rejected(self):
        assert validate_question_config({}) != []
        assert validate_question_config(None) != []  # type: ignore[arg-type]

    def test_missing_total_rejected(self):
        assert any("total" in e for e in validate_question_config({"easy": 5}))

    def test_zero_and_negative_total_rejected(self):
        assert validate_question_config({"total": 0}) != []
        assert validate_question_config({"total": -3}) != []

    def test_total_above_cap_rejected(self):
        assert validate_question_config({"total": 1000}) != []

    def test_difficulty_sum_mismatch_rejected(self):
        errors = validate_question_config({"total": 10, "easy": 2, "medium": 2, "hard": 2})
        assert any("sum" in e for e in errors)

    def test_type_sum_mismatch_rejected(self):
        errors = validate_question_config({"total": 10, "mcq": 3, "short_answer": 3})
        assert any("sum" in e for e in errors)

    def test_boolean_counts_rejected(self):
        assert validate_question_config({"total": True}) != []

    def test_material_selection_bounds(self):
        assert validate_material_selection(0) != []
        assert validate_material_selection(1) == []
        assert validate_material_selection(999) != []


class TestGeneratedExamValidation:
    def test_valid_output_passes(self):
        output = GeneratedExamOutput(questions=[_mcq() for _ in range(3)])
        assert validate_generated_exam(output, {"total": 3, "mcq": 3}) == []

    def test_empty_output_rejected(self):
        assert validate_generated_exam(GeneratedExamOutput(questions=[]), {"total": 3}) != []

    def test_count_mismatch_rejected(self):
        output = GeneratedExamOutput(questions=[_mcq()])
        assert any("Expected 3" in e for e in validate_generated_exam(output, {"total": 3}))

    def test_mcq_without_correct_option_rejected(self):
        output = GeneratedExamOutput(questions=[_mcq(correct=0)])
        errors = validate_generated_exam(output, {"total": 1})
        assert any("correct option" in e for e in errors)

    def test_true_false_shape_enforced(self):
        bad_tf = GeneratedQuestion(
            question_text="T/F",
            question_type=QuestionType.TRUE_FALSE,
            options=[GeneratedOption(option_text="True", is_correct=True)],
        )
        errors = validate_generated_exam(GeneratedExamOutput(questions=[bad_tf]), {"total": 1})
        assert any("exactly 2 options" in e for e in errors)

    def test_type_mix_enforced(self):
        output = GeneratedExamOutput(questions=[_mcq(), _mcq()])
        errors = validate_generated_exam(output, {"total": 2, "mcq": 1, "short_answer": 1})
        assert errors

    def test_difficulty_mix_enforced(self):
        output = GeneratedExamOutput(
            questions=[_mcq(difficulty=DifficultyLevel.EASY), _mcq(difficulty=DifficultyLevel.EASY)]
        )
        errors = validate_generated_exam(output, {"total": 2, "easy": 1, "hard": 1})
        assert errors
