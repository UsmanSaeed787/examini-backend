"""Strangler seam: plain async entry points existing routes call without
knowing about agents, runs, or the SDK (design §3, facade.py).

generate_exam() mirrors the legacy /api/teachers/exams/generate contract
exactly (same input schema, same persisted shape, same response model) while
replacing the model interaction with a guardrailed, budgeted, off-thread
agent run. Persistence is deterministic — the validated structured output is
written through ExamService, never by the model."""
import asyncio
import json

from app.ai.context import AIRunContext
from app.ai.guardrails.input import validate_material_selection, validate_question_config
from app.ai.runtime.runner import execute_run
from app.ai.schemas.outputs import GeneratedExamOutput
from app.ai.tools.materials import extract_teacher_material_texts
from app.middleware.error_handler import ValidationError
from app.models.exam import Exam
from app.models.user import User
from app.schemas.exam import ExamCreate, ExamGenerate, QuestionCreate, QuestionOptionCreate
from app.services.exam_service import ExamService


def _build_input(exam_data: ExamGenerate, texts: list[tuple[str, str]]) -> str:
    """Assemble the run input: config as data + clearly delimited material text."""
    parts = [
        "Generate exam questions from the course materials below.",
        f"Question configuration (must be followed exactly): {json.dumps(exam_data.question_config)}",
    ]
    for title, text in texts:
        parts.append(f"=== Material: {title} ===\n{text}")
    return "\n\n".join(parts)


def _to_exam_create(exam_data: ExamGenerate, output: GeneratedExamOutput) -> ExamCreate:
    questions = []
    for idx, q in enumerate(output.questions, 1):
        options = None
        if q.question_type.value in ("mcq", "true_false") and q.options:
            options = [
                QuestionOptionCreate(
                    option_text=opt.option_text,
                    is_correct=opt.is_correct,
                    order_number=opt.order_number or i + 1,
                )
                for i, opt in enumerate(q.options)
            ]
        questions.append(
            QuestionCreate(
                question_text=q.question_text,
                question_type=q.question_type,
                difficulty_level=q.difficulty_level,
                points=q.points,
                order_number=q.order_number or idx,
                options=options,
            )
        )
    return ExamCreate(
        title=exam_data.title,
        description=exam_data.description,
        class_id=exam_data.class_id,
        duration_minutes=exam_data.duration_minutes,
        start_date=exam_data.start_date,
        end_date=exam_data.end_date,
        allow_retake=exam_data.allow_retake,
        max_attempts=exam_data.max_attempts,
        questions=questions,
    )


async def generate_exam(current_user: User, exam_data: ExamGenerate) -> Exam:
    """Agent-backed replacement for the legacy generation path."""
    # 1. Deterministic input validation (previously absent — audit §12).
    errors = validate_question_config(exam_data.question_config)
    errors += validate_material_selection(len(exam_data.material_ids))
    if errors:
        raise ValidationError("; ".join(errors))

    # 2. Material ownership + text extraction, off the event loop.
    texts = await asyncio.to_thread(
        extract_teacher_material_texts, current_user.id, exam_data.material_ids
    )

    # 3. Guardrailed agent run (quotas, timeout, structured output).
    context = AIRunContext(
        user_id=current_user.id,
        role=current_user.role,
        full_name=current_user.full_name,
        extra={
            "question_config": exam_data.question_config,
            "class_id": str(exam_data.class_id),  # Context Engine course-facet hint
        },
    )
    outcome = await execute_run(context, "exam_generator", _build_input(exam_data, texts))
    output: GeneratedExamOutput = outcome.final_output

    # 4. Deterministic persistence through the existing service.
    exam_create = _to_exam_create(exam_data, output)
    return await asyncio.to_thread(_persist, exam_create, current_user.id)


def _persist(exam_create: ExamCreate, teacher_id) -> Exam:
    from app.database import SessionLocal

    with SessionLocal() as db:
        return ExamService.create_exam(db, exam_create, teacher_id)
