"""Materialization: the approved AssessmentPlan becomes a real exam.

This is the workflow's *consumer*, not a sixth stage (ASSESSMENT_WORKFLOW_DESIGN
§6): the planning pipeline still ends at COMPLETED, and this module reads that
terminal result and drives the existing `exam_generator` -> `ExamService`
path. It closes the last three steps of the product flow — AI generates
questions, quality is validated, the teacher publishes.

Three properties hold here, in descending order of importance:

1. **Publishing is a human action.** No agent has a publish tool, no model
   output carries a publish field, and PUBLISHED is reachable only from
   GENERATED via publish_assessment(), which is called only by the teacher's
   own HTTP request. Generation always produces an UNPUBLISHED draft.
2. **The model never writes rows.** The agent returns structured output; the
   validated result is persisted deterministically through ExamService,
   exactly as the legacy facade does.
3. **Generation follows what was approved.** The count skeleton comes from
   the approved blueprint, not the raw creation request — after rejections
   and config_patch corrections the two legitimately differ.

Same concurrency discipline as the rest of the layer: async at the surface,
each DB step a small sync function run via asyncio.to_thread, no session held
across an await.
"""
import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from app.ai.config import ai_settings
from app.ai.guardrails.output import (
    blueprint_question_config,
    validate_generated_against_blueprint,
)
from app.ai.schemas.outputs import GeneratedExamOutput
from app.ai.tools.materials import extract_teacher_material_texts
from app.ai.workflows.assessment.domain import GenerationStatus, WorkflowState
from app.ai.workflows.assessment.persistence import AIWorkflow, AIWorkflowGeneration
from app.ai.workflows.assessment.schemas import (
    AssessmentPlan,
    GenerationHistoryResponse,
    GenerationResponse,
)
from app.ai.workflows.assessment.state_machine import ensure_generation_transition
from app.database import SessionLocal
from app.middleware.error_handler import NotFoundError, ValidationError
from app.schemas.exam import ExamCreate, QuestionCreate, QuestionOptionCreate
from app.services.exam_service import ExamService

# Statuses that still own the workflow's materialization slot. A new attempt
# supersedes them; PUBLISHED is terminal and blocks a new attempt entirely.
_SUPERSEDABLE = frozenset(
    {GenerationStatus.PENDING, GenerationStatus.GENERATED, GenerationStatus.FAILED}
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _require_enabled() -> None:
    if not ai_settings.enabled:
        raise ValidationError("The AI layer is disabled (AI_ENABLED=false)")
    if not ai_settings.use_materialization:
        raise ValidationError(
            "Assessment materialization is disabled (AI_USE_MATERIALIZATION=false)"
        )


# ================================================================ plan gating

def parse_plan(workflow: AIWorkflow) -> AssessmentPlan:
    if not workflow.result:
        raise ValidationError("Workflow has no approved assessment plan")
    return AssessmentPlan.model_validate(workflow.result)


def plan_blockers(plan: AssessmentPlan) -> list[str]:
    """Reasons this approved plan must not be turned into an exam.

    The quality gate is deliberately re-read here rather than trusted from
    the stage's pass/fail alone: a plan can only be materialized if the
    quality review passed AND no upstream stage left a blocker standing."""
    blockers: list[str] = []
    if not plan.quality.passed:
        blockers.append("The quality review did not pass")
    for finding in plan.quality.findings:
        if finding.severity == "blocker":
            blockers.append(f"Unresolved quality blocker: {finding.message}")
    for finding in plan.schedule.findings:
        if finding.severity == "blocker":
            blockers.append(f"Unresolved scheduling blocker: {finding.message}")
    if plan.schedule.readiness == "blocked":
        blockers.append("The scheduler marked this exam window as blocked")
    if plan.blueprint.total_questions < 1:
        blockers.append("The blueprint contains no questions")
    if plan.blueprint.validation_errors:
        blockers.append(
            "The blueprint has unresolved validation errors: "
            + "; ".join(plan.blueprint.validation_errors)
        )
    return blockers


def resolve_duration(plan: AssessmentPlan) -> int:
    """The teacher's duration wins; the scheduler's estimate is the fallback.
    `recommended_duration_minutes` is advisory only and never applied here —
    the same rule merge_schedule_plan enforces upstream."""
    for candidate in (
        plan.schedule.duration_minutes,
        plan.schedule.estimated_duration_minutes,
    ):
        if candidate and candidate > 0:
            return int(candidate)
    raise ValidationError(
        "The plan has no exam duration; set duration_minutes on the workflow "
        "and re-run the scheduling stage"
    )


# ================================================================ sync DB steps

def _load(db, workflow_id: UUID, user_id: UUID) -> AIWorkflow:
    workflow = (
        db.query(AIWorkflow)
        .filter(AIWorkflow.id == workflow_id, AIWorkflow.user_id == user_id)
        .first()
    )
    if not workflow:
        raise NotFoundError("Workflow not found")
    return workflow


def _attempts(db, workflow_id: UUID) -> list[AIWorkflowGeneration]:
    return (
        db.query(AIWorkflowGeneration)
        .filter(AIWorkflowGeneration.workflow_id == workflow_id)
        .order_by(AIWorkflowGeneration.attempt.desc())
        .all()
    )


def _to_response(workflow_id: UUID, row: AIWorkflowGeneration) -> GenerationResponse:
    status = GenerationStatus(row.status)
    return GenerationResponse(
        workflow_id=workflow_id,
        status=status,
        attempt=row.attempt,
        exam_id=row.exam_id,
        run_id=row.run_id,
        question_count=row.question_count or 0,
        findings=list(row.findings or []),
        error=row.error,
        is_published=status == GenerationStatus.PUBLISHED,
        created_at=row.created_at,
        generated_at=row.generated_at,
        published_at=row.published_at,
    )


def _open_attempt_sync(workflow_id: UUID, user_id: UUID) -> tuple[UUID, dict, str]:
    """Validate the workflow is materializable and claim a new attempt row.

    Returns (generation_id, plan_json, workflow_title). The row is left in
    GENERATING so a second concurrent request is rejected rather than racing."""
    with SessionLocal() as db:
        workflow = _load(db, workflow_id, user_id)
        if WorkflowState(workflow.state) != WorkflowState.COMPLETED:
            raise ValidationError(
                f"Workflow is '{workflow.state}'; only a completed workflow with an "
                "approved plan can be turned into an exam"
            )
        plan = parse_plan(workflow)
        blockers = plan_blockers(plan)
        if blockers:
            raise ValidationError(
                "This plan cannot be materialized: " + "; ".join(blockers)
            )
        resolve_duration(plan)  # fail before spending a model call

        existing = _attempts(db, workflow_id)
        latest = existing[0] if existing else None
        if latest is not None:
            status = GenerationStatus(latest.status)
            if status == GenerationStatus.PUBLISHED:
                raise ValidationError(
                    "This assessment is already published; unpublish the exam before "
                    "regenerating it"
                )
            if status == GenerationStatus.GENERATING:
                raise ValidationError("A generation is already in progress")
            if status in _SUPERSEDABLE:
                # The previous draft exam (if any) is intentionally left in
                # place — deleting a teacher's exam is never implicit. It is
                # removable through the normal exam endpoints.
                ensure_generation_transition(status, GenerationStatus.SUPERSEDED)
                latest.status = GenerationStatus.SUPERSEDED.value

        row = AIWorkflowGeneration(
            workflow_id=workflow_id,
            user_id=user_id,
            status=GenerationStatus.GENERATING.value,
            attempt=(latest.attempt + 1) if latest else 1,
            findings=[],
        )
        db.add(row)
        try:
            db.commit()
        except IntegrityError:
            # uq_workflow_generation_attempt: a concurrent request claimed
            # this attempt number first. The constraint — not the read above —
            # is what actually serializes double-submits.
            db.rollback()
            raise ValidationError("A generation is already in progress")
        return row.id, dict(workflow.result), workflow.title


def _persist_sync(
    generation_id: UUID,
    user_id: UUID,
    exam_create: ExamCreate,
    findings: list[str],
    run_id: Optional[UUID],
) -> UUID:
    """Write the exam through ExamService (as an unpublished draft) and close
    out the attempt row."""
    with SessionLocal() as db:
        # create_exam commits its own transaction; closing out the attempt row
        # in the same session keeps the window where an exam exists without an
        # audit link as small as a single statement.
        exam_id = ExamService.create_exam(db, exam_create, user_id).id
        row = db.query(AIWorkflowGeneration).filter(
            AIWorkflowGeneration.id == generation_id
        ).first()
        if row is None:
            raise NotFoundError("Generation record not found")
        ensure_generation_transition(
            GenerationStatus(row.status), GenerationStatus.GENERATED
        )
        row.status = GenerationStatus.GENERATED.value
        row.exam_id = exam_id
        row.run_id = run_id
        row.question_count = len(exam_create.questions)
        row.findings = findings
        row.generated_at = _now()
        db.commit()
    return exam_id


def _fail_sync(generation_id: UUID, error: str) -> None:
    with SessionLocal() as db:
        row = db.query(AIWorkflowGeneration).filter(
            AIWorkflowGeneration.id == generation_id
        ).first()
        if row is None:
            return
        if GenerationStatus(row.status) == GenerationStatus.GENERATING:
            row.status = GenerationStatus.FAILED.value
            row.error = error[:2000]
            db.commit()


def _publish_sync(
    workflow_id: UUID, user_id: UUID, acknowledge_findings: bool
) -> GenerationResponse:
    """The one place an assessment becomes visible to students. Reached only
    from an explicit teacher request — never from a stage, handler, or agent."""
    with SessionLocal() as db:
        _load(db, workflow_id, user_id)  # ownership
        existing = _attempts(db, workflow_id)
        if not existing:
            raise ValidationError("Nothing has been generated for this workflow yet")
        row = existing[0]
        status = GenerationStatus(row.status)
        if status == GenerationStatus.PUBLISHED:
            raise ValidationError("This assessment is already published")
        ensure_generation_transition(status, GenerationStatus.PUBLISHED)
        if not row.exam_id:
            raise ValidationError("The generated exam is no longer available")
        findings = list(row.findings or [])
        if findings and not acknowledge_findings:
            raise ValidationError(
                "The generated exam has unresolved validation findings; re-send with "
                "acknowledge_findings=true to publish anyway: " + "; ".join(findings)
            )
        if not row.question_count:
            raise ValidationError("Refusing to publish an exam with no questions")

        exam = ExamService.get_exam(db, row.exam_id)
        if exam.teacher_id != user_id:
            raise NotFoundError("Exam not found")
        ExamService.publish_exam(db, row.exam_id, True)

        row.status = GenerationStatus.PUBLISHED.value
        row.published_at = _now()
        db.commit()
        return _to_response(workflow_id, row)


def _reclaim_stale(db, rows: list[AIWorkflowGeneration]) -> None:
    """Fail an attempt abandoned by a worker that died mid-generation.

    Mirrors the workflow's stage reclamation: generation runs detached and
    in-process, so a restart would otherwise leave the row GENERATING forever
    and the UI spinning. Lazy — the only moment it matters is on read."""
    from app.ai.config import ai_settings

    if not rows:
        return
    row = rows[0]
    if GenerationStatus(row.status) != GenerationStatus.GENERATING or row.created_at is None:
        return
    started = row.created_at
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    limit = timedelta(seconds=ai_settings.run_timeout_seconds * 2 + 60)
    if _now() - started < limit:
        return
    row.status = GenerationStatus.FAILED.value
    row.error = (
        "Question generation stopped unexpectedly — the server restarted while it "
        "was running. No exam was created; you can generate again."
    )
    db.commit()


def _history_sync(workflow_id: UUID, user_id: UUID) -> GenerationHistoryResponse:
    with SessionLocal() as db:
        _load(db, workflow_id, user_id)  # ownership
        rows = _attempts(db, workflow_id)
        _reclaim_stale(db, rows)
        attempts = [_to_response(workflow_id, row) for row in rows]
        return GenerationHistoryResponse(
            workflow_id=workflow_id,
            current=attempts[0] if attempts else None,
            attempts=attempts,
        )


# ================================================================ generation

def build_generation_input(plan: AssessmentPlan, texts: list[tuple[str, str]]) -> str:
    """Assemble the run input: the approved blueprint as data + clearly
    delimited material text (material content is data, never instructions)."""
    parts = [
        "Generate the exam questions for an assessment plan a teacher has already "
        "reviewed and approved. Follow the blueprint exactly.",
        f"Question configuration (must be followed exactly): "
        f"{json.dumps(blueprint_question_config(plan.blueprint))}",
    ]
    if plan.blueprint.topic_allocations:
        parts.append(
            "Topic allocation plan — produce exactly this many questions per topic "
            "and tag each question with its topic:\n"
            + json.dumps(
                [a.model_dump(mode="json") for a in plan.blueprint.topic_allocations],
                indent=2,
            )
        )
    if plan.blueprint.rationale:
        parts.append(f"Design rationale: {plan.blueprint.rationale}")
    if plan.outline.summary:
        parts.append(f"Curriculum summary: {plan.outline.summary}")
    for title, text in texts:
        parts.append(f"=== Material: {title} ===\n{text}")
    return "\n\n".join(parts)


def to_exam_create(
    plan: AssessmentPlan,
    title: str,
    duration_minutes: int,
    output: GeneratedExamOutput,
) -> ExamCreate:
    """Deterministic projection of validated model output onto the platform's
    own creation schema. `topic` is a generation-time verification signal and
    is intentionally not persisted — the exam schema has no topic column."""
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
        title=title,
        description=plan.blueprint.rationale or plan.outline.summary,
        class_id=UUID(plan.class_id),
        duration_minutes=duration_minutes,
        start_date=plan.schedule.proposed_start,
        end_date=plan.schedule.proposed_end,
        questions=questions,
    )


async def generate_assessment(
    user_id: UUID, workflow_id: UUID, *, background: bool = True
) -> GenerationResponse:
    """Turn the approved plan into an UNPUBLISHED draft exam.

    The attempt row is claimed synchronously — so the caller immediately sees
    `generating` and a second request is rejected — and the model run itself is
    detached. This is the longest call in the product (a full generation over
    every material's text); holding a request open for it is what made progress
    unreportable.

    `background=False` awaits completion, for scripts and tests."""
    _require_enabled()
    generation_id, plan_json, title = await asyncio.to_thread(
        _open_attempt_sync, workflow_id, user_id
    )
    work = _materialize(generation_id, user_id, workflow_id, plan_json, title)
    if background:
        from app.ai.jobs.tasks import spawn

        spawn(work, label=f"generate:{workflow_id}")
    else:
        await work
    return await get_generation(user_id, workflow_id)


async def _materialize(
    generation_id: UUID,
    user_id: UUID,
    workflow_id: UUID,
    plan_json: dict,
    title: str,
) -> None:
    """The heavy half: read materials, run the generator, persist the draft."""
    from app.ai.context import AIRunContext
    from app.ai.runtime.runner import execute_run

    try:
        plan = AssessmentPlan.model_validate(plan_json)
        duration = resolve_duration(plan)
        material_ids = [UUID(unit.material_id) for unit in plan.outline.units if unit.parseable]
        if not material_ids:
            raise ValidationError(
                "No approved material has extractable text to generate questions from"
            )
        texts = await asyncio.to_thread(
            extract_teacher_material_texts, user_id, material_ids
        )

        context = AIRunContext(
            user_id=user_id,
            role="teacher",
            extra={
                # The blueprint (not the raw request) is what the generator's
                # guardrails validate against.
                "question_config": blueprint_question_config(plan.blueprint),
                "class_id": plan.class_id,
                "workflow_id": str(workflow_id),
            },
        )
        outcome = await execute_run(
            context, "exam_generator", build_generation_input(plan, texts)
        )
        output: GeneratedExamOutput = outcome.final_output

        # Post-generation quality validation. Counts and option integrity are
        # already tripwires on the agent; what survives to here is the
        # blueprint-level deviation a teacher should see before publishing.
        findings = validate_generated_against_blueprint(output, plan.blueprint)

        exam_create = to_exam_create(plan, title, duration, output)
        await asyncio.to_thread(
            _persist_sync,
            generation_id,
            user_id,
            exam_create,
            findings,
            outcome.run_id,
        )
    except Exception as exc:  # noqa: BLE001 - recorded, then re-raised
        # describe_error unpacks a guardrail rejection into the specific checks
        # that failed, so the teacher sees a reason rather than "validation".
        from app.ai.runtime.exceptions import describe_error

        await asyncio.to_thread(_fail_sync, generation_id, describe_error(exc))
        raise


async def publish_assessment(
    user_id: UUID, workflow_id: UUID, acknowledge_findings: bool = False
) -> GenerationResponse:
    """Release the generated exam to students. Human-invoked only."""
    return await asyncio.to_thread(
        _publish_sync, workflow_id, user_id, acknowledge_findings
    )


async def get_generation(user_id: UUID, workflow_id: UUID) -> GenerationResponse:
    history = await asyncio.to_thread(_history_sync, workflow_id, user_id)
    if history.current is None:
        raise NotFoundError("Nothing has been generated for this workflow yet")
    return history.current


async def get_generation_history(
    user_id: UUID, workflow_id: UUID
) -> GenerationHistoryResponse:
    return await asyncio.to_thread(_history_sync, workflow_id, user_id)
