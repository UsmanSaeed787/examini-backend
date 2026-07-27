"""Assessment workflow orchestrator.

The ONLY component that mutates workflow state, and every mutation goes
through state_machine guards. Async at the surface; each DB step is a small
synchronous function run via asyncio.to_thread (same non-blocking discipline
as the tool layer). Handlers execute between DB steps and never hold a
session open across an await.

Auto-advance semantics: after a stage completes, either it stops at a human
checkpoint (per ApprovalMode) or it is auto-approved and the next stage runs
immediately. approve()/reject() resume the same loop.
"""
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from app.ai.workflows.assessment import stages as stage_registry
from app.ai.guardrails.input import validate_question_config
from app.ai.workflows.assessment.domain import (
    ADJUSTABLE_FROM,
    DETERMINISTIC_RERUN_KEY,
    ApprovalMode,
    CheckpointDecision,
    GenerationStatus,
    StageKey,
    StageStatus,
    WorkflowState,
)
from app.ai.workflows.assessment.persistence import (
    AIWorkflow,
    AIWorkflowCheckpoint,
    AIWorkflowGeneration,
    AIWorkflowStage,
)
from app.ai.workflows.assessment.schemas import (
    ARTIFACT_TYPES,
    AssessmentPlan,
    CreateWorkflowRequest,
    StageResponse,
    WorkflowResponse,
    WorkflowSummaryResponse,
)
from app.ai.workflows.assessment.state_machine import (
    checkpoint_required,
    ensure_generation_transition,
    ensure_stage_invalidation,
    ensure_stage_transition,
    ensure_workflow_transition,
    next_stage,
)
from app.ai.runtime.errors import AIError
from app.ai.runtime.execution import PipelineExecutor
from app.ai.runtime.interfaces import StagePlan
from app.ai.runtime.registry import WorkflowDefinition, workflow_registry
from app.database import SessionLocal
from app.middleware.error_handler import NotFoundError, ValidationError
from app.utils.constants import UserRole


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _pipeline() -> tuple[StageKey, ...]:
    return stage_registry.registered_pipeline()


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


def _stage_row(db, workflow_id: UUID, stage_key: StageKey) -> AIWorkflowStage:
    row = (
        db.query(AIWorkflowStage)
        .filter(
            AIWorkflowStage.workflow_id == workflow_id,
            AIWorkflowStage.stage_key == stage_key.value,
        )
        .first()
    )
    if not row:
        raise NotFoundError(f"Stage '{stage_key.value}' not found")
    return row


def _create_sync(user_id: UUID, payload: CreateWorkflowRequest) -> UUID:
    from app.services.class_service import ClassService
    from app.services.material_service import MaterialService

    with SessionLocal() as db:
        ClassService.get_class(db, payload.class_id)  # NotFoundError if absent
        owned = MaterialService.get_materials_by_ids(db, payload.material_ids, user_id)
        if len(owned) != len(payload.material_ids):
            raise ValidationError("Some materials not found or not accessible")

        workflow = AIWorkflow(
            user_id=user_id,
            kind="assessment",
            class_id=payload.class_id,
            title=payload.title,
            state=WorkflowState.DRAFT.value,
            approval_mode=payload.approval_mode.value,
            config={
                "material_ids": [str(m) for m in payload.material_ids],
                "question_config": payload.question_config,
                "duration_minutes": payload.duration_minutes,
                "proposed_start": payload.proposed_start.isoformat() if payload.proposed_start else None,
                "proposed_end": payload.proposed_end.isoformat() if payload.proposed_end else None,
            },
        )
        db.add(workflow)
        db.flush()
        for sequence, stage in enumerate(_pipeline(), 1):
            db.add(
                AIWorkflowStage(
                    workflow_id=workflow.id,
                    stage_key=stage.value,
                    sequence=sequence,
                    status=StageStatus.PENDING.value,
                )
            )
        db.commit()
        return workflow.id


def _start_sync(workflow_id: UUID, user_id: UUID) -> None:
    with SessionLocal() as db:
        workflow = _load(db, workflow_id, user_id)
        ensure_workflow_transition(WorkflowState(workflow.state), WorkflowState.IN_PROGRESS)
        workflow.state = WorkflowState.IN_PROGRESS.value
        workflow.current_stage = _pipeline()[0].value
        workflow.updated_at = _now()
        db.commit()


def _begin_stage_sync(workflow_id: UUID, user_id: UUID) -> Optional[stage_registry.StageContext]:
    """Mark the current stage RUNNING and return its execution context.
    Returns None when the workflow is not in a runnable position."""
    with SessionLocal() as db:
        workflow = _load(db, workflow_id, user_id)
        if WorkflowState(workflow.state) != WorkflowState.IN_PROGRESS or not workflow.current_stage:
            return None
        stage = _stage_row(db, workflow_id, StageKey(workflow.current_stage))
        if StageStatus(stage.status) != StageStatus.PENDING:
            return None
        ensure_stage_transition(StageStatus(stage.status), StageStatus.RUNNING)
        stage.status = StageStatus.RUNNING.value
        stage.started_at = _now()
        workflow.updated_at = _now()

        prior = {
            row.stage_key: row.artifact
            for row in db.query(AIWorkflowStage)
            .filter(
                AIWorkflowStage.workflow_id == workflow_id,
                AIWorkflowStage.status == StageStatus.APPROVED.value,
            )
            .all()
            if row.artifact is not None
        }
        context = stage_registry.StageContext(
            workflow_id=workflow_id,
            user_id=user_id,
            role="teacher",
            class_id=workflow.class_id,
            config=dict(workflow.config or {}),
            revision=stage.revision,
            prior_artifacts=prior,
            rejection_notes=stage.notes,
            # Set by an adjustment; travels in the config because the pipeline
            # runs detached and must outlive the request that set it.
            deterministic_only=bool((workflow.config or {}).get(DETERMINISTIC_RERUN_KEY)),
        )
        db.commit()
        return context


def _finish_stage_sync(
    workflow_id: UUID,
    user_id: UUID,
    stage_key: StageKey,
    artifact: dict,
    stop_for_review: bool,
    run_id: Optional[UUID] = None,
) -> None:
    with SessionLocal() as db:
        workflow = _load(db, workflow_id, user_id)
        stage = _stage_row(db, workflow_id, stage_key)
        target = StageStatus.IN_REVIEW if stop_for_review else StageStatus.APPROVED
        ensure_stage_transition(StageStatus(stage.status), target)
        stage.status = target.value
        stage.artifact = artifact
        stage.run_id = run_id  # links agent-produced artifacts to their ai_runs record
        stage.completed_at = _now()
        if stop_for_review:
            ensure_workflow_transition(WorkflowState(workflow.state), WorkflowState.AWAITING_APPROVAL)
            workflow.state = WorkflowState.AWAITING_APPROVAL.value
        else:
            _advance_pointer(db, workflow, stage_key)
        workflow.updated_at = _now()
        db.commit()


def _advance_pointer(db, workflow: AIWorkflow, approved_stage: StageKey) -> None:
    """After an approval, point the workflow at the next stage or complete it."""
    following = next_stage(approved_stage, _pipeline())
    if following is not None:
        ensure_workflow_transition(WorkflowState(workflow.state), WorkflowState.IN_PROGRESS)
        workflow.state = WorkflowState.IN_PROGRESS.value
        workflow.current_stage = following.value
        return
    ensure_workflow_transition(WorkflowState(workflow.state), WorkflowState.COMPLETED)
    artifacts = {
        row.stage_key: row.artifact
        for row in db.query(AIWorkflowStage)
        .filter(AIWorkflowStage.workflow_id == workflow.id)
        .all()
        if row.artifact is not None
    }
    plan = AssessmentPlan(
        workflow_id=str(workflow.id),
        title=workflow.title,
        class_id=str(workflow.class_id),
        outline=artifacts[StageKey.CURRICULUM_ANALYSIS.value],
        blueprint=artifacts[StageKey.ASSESSMENT_DESIGN.value],
        quality=artifacts[StageKey.QUALITY_REVIEW.value],
        difficulty=artifacts[StageKey.DIFFICULTY_ANALYSIS.value],
        schedule=artifacts[StageKey.SCHEDULING.value],
        approved_at=_now(),
    )
    workflow.state = WorkflowState.COMPLETED.value
    workflow.current_stage = None
    workflow.result = plan.model_dump(mode="json")
    workflow.finished_at = _now()


def _decide_sync(
    workflow_id: UUID,
    user_id: UUID,
    stage_key: StageKey,
    decision: CheckpointDecision,
    notes: Optional[str],
    config_patch: Optional[dict],
) -> None:
    with SessionLocal() as db:
        workflow = _load(db, workflow_id, user_id)
        stage = _stage_row(db, workflow_id, stage_key)
        if StageStatus(stage.status) != StageStatus.IN_REVIEW:
            raise ValidationError(f"Stage '{stage_key.value}' is not awaiting approval")

        db.add(
            AIWorkflowCheckpoint(
                workflow_id=workflow_id,
                stage_key=stage_key.value,
                revision=stage.revision,
                decision=decision.value,
                decided_by=user_id,
                notes=notes,
            )
        )
        if decision == CheckpointDecision.APPROVED:
            ensure_stage_transition(StageStatus(stage.status), StageStatus.APPROVED)
            stage.status = StageStatus.APPROVED.value
            stage.notes = notes
            _advance_pointer(db, workflow, stage_key)
        else:
            ensure_stage_transition(StageStatus(stage.status), StageStatus.REJECTED)
            ensure_stage_transition(StageStatus.REJECTED, StageStatus.PENDING)
            # Workflow Memory: keep the reviewer's rejection feedback so
            # future (agent-backed) stage runs can recall why revisions
            # happened. Memory failure must never break the decision.
            try:
                from app.ai.memory.service import memory_service

                memory_service.remember_workflow(
                    workflow_id,
                    user_id,
                    key=f"rejection:{stage_key.value}:rev{stage.revision}",
                    content={
                        "stage": stage_key.value,
                        "revision": stage.revision,
                        "notes": notes,
                    },
                )
            except Exception:  # noqa: BLE001
                pass
            stage.status = StageStatus.PENDING.value
            stage.revision += 1
            stage.notes = notes
            stage.artifact = None
            stage.completed_at = None
            if config_patch:
                merged = dict(workflow.config or {})
                merged.update(config_patch)
                workflow.config = merged
            ensure_workflow_transition(WorkflowState(workflow.state), WorkflowState.IN_PROGRESS)
            workflow.state = WorkflowState.IN_PROGRESS.value
            workflow.current_stage = stage_key.value
        workflow.updated_at = _now()
        db.commit()


def _supersede_generations(db, workflow_id: UUID) -> None:
    """Retire any draft exam produced from the mix that is about to change.

    Mirrors what regeneration already does in materialization._open_attempt_sync:
    a published assessment is off limits, and an unpublished attempt is marked
    SUPERSEDED rather than deleted — the draft exam itself is left alone, because
    removing a teacher's exam is never implicit."""
    rows = (
        db.query(AIWorkflowGeneration)
        .filter(AIWorkflowGeneration.workflow_id == workflow_id)
        .order_by(AIWorkflowGeneration.attempt.desc())
        .all()
    )
    if not rows:
        return
    latest = GenerationStatus(rows[0].status)
    if latest == GenerationStatus.PUBLISHED:
        raise ValidationError(
            "This assessment is already published; unpublish the exam before "
            "changing its question mix"
        )
    if latest == GenerationStatus.GENERATING:
        raise ValidationError("Questions are being generated; wait for that to finish")
    for row in rows:
        status = GenerationStatus(row.status)
        if status in (
            GenerationStatus.PENDING,
            GenerationStatus.GENERATED,
            GenerationStatus.FAILED,
        ):
            ensure_generation_transition(status, GenerationStatus.SUPERSEDED)
            row.status = GenerationStatus.SUPERSEDED.value


def _adjust_sync(workflow_id: UUID, user_id: UUID, question_config: dict) -> None:
    """Apply a teacher's edit to the question mix and re-open what it invalidates.

    This is the cheap counterpart to rejection. Rejection says "AI, think again"
    and costs a model run; adjustment says "these are the numbers now" and costs
    nothing — the affected stages recompute from their deterministic cores.

    Stages from ASSESSMENT_DESIGN onward are re-opened because each derives from
    the mix (the blueprint directly, quality from the blueprint, difficulty from
    the target distribution, scheduling from the question types). Curriculum
    analysis is untouched: the materials did not change."""
    errors = validate_question_config(question_config or {})
    if errors:
        raise ValidationError("; ".join(errors))

    with SessionLocal() as db:
        workflow = _load(db, workflow_id, user_id)
        state = WorkflowState(workflow.state)
        if state in (WorkflowState.CANCELLED, WorkflowState.FAILED):
            raise ValidationError(
                f"This assessment is {state.value}; its question mix can no longer be changed"
            )
        # COMPLETED is deliberately allowed. Approving the plan should not be the
        # moment the numbers freeze — the teacher is then looking at the Generate
        # step, which is exactly when "actually, make it 12" occurs to them.
        if state == WorkflowState.COMPLETED:
            _supersede_generations(db, workflow_id)

        pipeline = _pipeline()
        start = pipeline.index(ADJUSTABLE_FROM)
        affected = pipeline[start:]

        rows = {
            row.stage_key: row
            for row in db.query(AIWorkflowStage)
            .filter(AIWorkflowStage.workflow_id == workflow_id)
            .all()
        }
        for stage in affected:
            row = rows.get(stage.value)
            if row is None:
                continue
            ensure_stage_invalidation(StageStatus(row.status))

        # Audited: an adjustment is a third kind of checkpoint decision, and the
        # plan that was approved is not the plan that now exists.
        db.add(
            AIWorkflowCheckpoint(
                workflow_id=workflow_id,
                stage_key=ADJUSTABLE_FROM.value,
                revision=rows[ADJUSTABLE_FROM.value].revision if ADJUSTABLE_FROM.value in rows else 1,
                decision=CheckpointDecision.ADJUSTED.value,
                decided_by=user_id,
                notes=f"Question mix changed to {question_config}",
            )
        )

        for stage in affected:
            row = rows.get(stage.value)
            if row is None:
                continue
            if StageStatus(row.status) != StageStatus.PENDING:
                row.revision += 1
            row.status = StageStatus.PENDING.value
            row.artifact = None
            row.completed_at = None
            row.run_id = None

        merged = dict(workflow.config or {})
        merged["question_config"] = question_config
        merged[DETERMINISTIC_RERUN_KEY] = True
        workflow.config = merged
        workflow.state = WorkflowState.IN_PROGRESS.value
        workflow.current_stage = ADJUSTABLE_FROM.value
        workflow.result = None  # the approved plan no longer describes reality
        workflow.error = None
        workflow.finished_at = None
        workflow.updated_at = _now()
        db.commit()


def _clear_deterministic_flag(workflow_id: UUID, user_id: UUID) -> None:
    """Drop the one-shot deterministic marker once the recompute has settled."""
    with SessionLocal() as db:
        workflow = _load(db, workflow_id, user_id)
        config = dict(workflow.config or {})
        if config.pop(DETERMINISTIC_RERUN_KEY, None) is not None:
            workflow.config = config
            db.commit()


def _fail_sync(workflow_id: UUID, user_id: UUID, stage_key: StageKey, error: str) -> None:
    with SessionLocal() as db:
        workflow = _load(db, workflow_id, user_id)
        stage = _stage_row(db, workflow_id, stage_key)
        ensure_stage_transition(StageStatus(stage.status), StageStatus.FAILED)
        stage.status = StageStatus.FAILED.value
        ensure_workflow_transition(WorkflowState(workflow.state), WorkflowState.FAILED)
        workflow.state = WorkflowState.FAILED.value
        workflow.error = error[:2000]
        workflow.finished_at = _now()
        workflow.updated_at = _now()
        db.commit()


def _cancel_sync(workflow_id: UUID, user_id: UUID) -> None:
    with SessionLocal() as db:
        workflow = _load(db, workflow_id, user_id)
        ensure_workflow_transition(WorkflowState(workflow.state), WorkflowState.CANCELLED)
        workflow.state = WorkflowState.CANCELLED.value
        workflow.finished_at = _now()
        workflow.updated_at = _now()
        db.commit()


def _stale_after() -> timedelta:
    """How long a RUNNING stage may sit before we presume its worker died.

    Generous on purpose: a legitimately slow stage must never be reclaimed out
    from under itself, so this is twice the run timeout plus a margin."""
    from app.ai.config import ai_settings

    return timedelta(seconds=ai_settings.run_timeout_seconds * 2 + 60)


def _reclaim_stale(db, workflow: AIWorkflow) -> bool:
    """Fail a stage abandoned by a worker that died mid-run.

    Background execution is in-process, so a restart or crash leaves a stage
    RUNNING with nothing driving it — it would otherwise spin forever in the
    UI. Reclamation is lazy (done on read) rather than scheduled: the only
    moment it matters is when somebody looks."""
    if WorkflowState(workflow.state) != WorkflowState.IN_PROGRESS:
        return False
    row = (
        db.query(AIWorkflowStage)
        .filter(
            AIWorkflowStage.workflow_id == workflow.id,
            AIWorkflowStage.status == StageStatus.RUNNING.value,
        )
        .first()
    )
    if row is None or row.started_at is None:
        return False
    started = row.started_at
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    if _now() - started < _stale_after():
        return False

    row.status = StageStatus.FAILED.value
    workflow.state = WorkflowState.FAILED.value
    workflow.error = (
        f"The '{row.stage_key}' step stopped unexpectedly — the server restarted "
        "while it was running. Nothing was saved for this step; start it again."
    )
    workflow.finished_at = _now()
    workflow.updated_at = _now()
    db.commit()
    return True


def _snapshot_sync(workflow_id: UUID, user_id: UUID) -> WorkflowResponse:
    with SessionLocal() as db:
        workflow = _load(db, workflow_id, user_id)
        _reclaim_stale(db, workflow)
        mode = ApprovalMode(workflow.approval_mode)
        rows = (
            db.query(AIWorkflowStage)
            .filter(AIWorkflowStage.workflow_id == workflow_id)
            .order_by(AIWorkflowStage.sequence)
            .all()
        )
        return WorkflowResponse(
            id=workflow.id,
            title=workflow.title,
            state=WorkflowState(workflow.state),
            current_stage=StageKey(workflow.current_stage) if workflow.current_stage else None,
            approval_mode=mode,
            class_id=workflow.class_id,
            config=dict(workflow.config or {}),
            stages=[
                StageResponse(
                    stage_key=StageKey(row.stage_key),
                    sequence=row.sequence,
                    status=StageStatus(row.status),
                    revision=row.revision,
                    requires_checkpoint=checkpoint_required(mode, StageKey(row.stage_key), _pipeline()),
                    artifact=row.artifact,
                    notes=row.notes,
                    started_at=row.started_at,
                    completed_at=row.completed_at,
                )
                for row in rows
            ],
            result=workflow.result,
            error=workflow.error,
            created_at=workflow.created_at,
            finished_at=workflow.finished_at,
        )


def _list_sync(user_id: UUID) -> list[WorkflowSummaryResponse]:
    with SessionLocal() as db:
        rows = (
            db.query(AIWorkflow)
            .filter(AIWorkflow.user_id == user_id, AIWorkflow.kind == "assessment")
            .order_by(AIWorkflow.created_at.desc())
            .limit(50)
            .all()
        )
        return [
            WorkflowSummaryResponse(
                id=row.id,
                title=row.title,
                state=WorkflowState(row.state),
                current_stage=StageKey(row.current_stage) if row.current_stage else None,
                created_at=row.created_at,
            )
            for row in rows
        ]


# ================================================================ async surface

class _AssessmentHooks:
    """PipelineHooks implementation binding the kernel's generic
    PipelineExecutor to this workflow's persistence and checkpoint policy.
    The kernel owns the loop/instrumentation; these hooks own the state."""

    def __init__(self, workflow_id: UUID, user_id: UUID):
        self.workflow_id = workflow_id
        self.user_id = user_id

    async def begin_stage(self) -> Optional[StagePlan]:
        context = await asyncio.to_thread(_begin_stage_sync, self.workflow_id, self.user_id)
        if context is None:
            return None
        snapshot = await asyncio.to_thread(_snapshot_sync, self.workflow_id, self.user_id)
        if snapshot.current_stage is None:
            return None
        stage_key = StageKey(snapshot.current_stage)
        expected = ARTIFACT_TYPES[stage_key]

        def _validate(artifact) -> None:
            if not isinstance(artifact, expected):
                raise ValidationError(
                    f"Stage '{stage_key.value}' produced {type(artifact).__name__}, "
                    f"expected {expected.__name__}"
                )

        return StagePlan(
            stage_key=stage_key.value,
            handler=stage_registry.get_handler(stage_key),
            context=context,
            pause_after=checkpoint_required(
                ApprovalMode(snapshot.approval_mode), stage_key, _pipeline()
            ),
            validate=_validate,
        )

    async def complete_stage(self, plan: StagePlan, artifact, paused: bool) -> None:
        await asyncio.to_thread(
            _finish_stage_sync,
            self.workflow_id,
            self.user_id,
            StageKey(plan.stage_key),
            artifact.model_dump(mode="json"),
            paused,
            getattr(plan.context, "run_id", None),
        )

    async def fail_stage(self, plan: StagePlan, message: str) -> None:
        await asyncio.to_thread(
            _fail_sync, self.workflow_id, self.user_id, StageKey(plan.stage_key), message
        )


_EXECUTOR = PipelineExecutor(catch=(ValidationError, NotFoundError, AIError))


async def run_pipeline(workflow_id: UUID, user_id: UUID) -> None:
    """Run stages until a checkpoint pauses the pipeline or it completes.
    Failures are recorded by the hooks; the result is reflected in the
    workflow snapshot the caller re-reads."""
    try:
        await _EXECUTOR.run(_AssessmentHooks(workflow_id, user_id))
    finally:
        # One-shot: a deterministic recompute covers only the run it was
        # requested for. Cleared even on failure, so a later retry is not
        # silently stripped of its agents.
        await asyncio.to_thread(_clear_deterministic_flag, workflow_id, user_id)


async def _dispatch(workflow_id: UUID, user_id: UUID, background: bool) -> None:
    """Drive the pipeline, detached by default.

    Stages can each take minutes, and under `final_only`/`none` a single call
    runs the whole plan — far too long to hold an HTTP request open. Because
    `_begin_stage_sync` commits `status = running` BEFORE invoking a handler,
    the database already reports which stage is executing, so the client gets
    real progress by polling the ordinary GET endpoint. No new state, no job
    ids, no stream.

    `background=False` keeps the blocking path for scripts and tests that want
    to await completion."""
    if not background:
        await run_pipeline(workflow_id, user_id)
        return
    from app.ai.jobs.tasks import spawn

    spawn(run_pipeline(workflow_id, user_id), label=f"assessment:{workflow_id}")


async def create_workflow(user_id: UUID, payload: CreateWorkflowRequest) -> WorkflowResponse:
    workflow_id = await asyncio.to_thread(_create_sync, user_id, payload)
    return await asyncio.to_thread(_snapshot_sync, workflow_id, user_id)


async def start_workflow(
    user_id: UUID, workflow_id: UUID, *, background: bool = True
) -> WorkflowResponse:
    await asyncio.to_thread(_start_sync, workflow_id, user_id)
    await _dispatch(workflow_id, user_id, background)
    return await asyncio.to_thread(_snapshot_sync, workflow_id, user_id)


async def approve_stage(
    user_id: UUID,
    workflow_id: UUID,
    stage_key: StageKey,
    notes: Optional[str],
    *,
    background: bool = True,
) -> WorkflowResponse:
    await asyncio.to_thread(
        _decide_sync, workflow_id, user_id, stage_key, CheckpointDecision.APPROVED, notes, None
    )
    await _dispatch(workflow_id, user_id, background)
    return await asyncio.to_thread(_snapshot_sync, workflow_id, user_id)


async def reject_stage(
    user_id: UUID,
    workflow_id: UUID,
    stage_key: StageKey,
    notes: str,
    config_patch: Optional[dict],
    *,
    background: bool = True,
) -> WorkflowResponse:
    await asyncio.to_thread(
        _decide_sync,
        workflow_id,
        user_id,
        stage_key,
        CheckpointDecision.REJECTED,
        notes,
        config_patch,
    )
    await _dispatch(workflow_id, user_id, background)
    return await asyncio.to_thread(_snapshot_sync, workflow_id, user_id)


async def adjust_question_mix(
    user_id: UUID,
    workflow_id: UUID,
    question_config: dict,
    *,
    background: bool = True,
) -> WorkflowResponse:
    """Change the question mix and recompute — without a model call.

    The counterpart to reject_stage: rejection asks the AI to reconsider,
    adjustment states what the numbers now are. Everything derived from the mix
    is recomputed deterministically, which is fast, free, and predictable — the
    teacher gets exactly the counts they typed."""
    await asyncio.to_thread(_adjust_sync, workflow_id, user_id, question_config)
    await _dispatch(workflow_id, user_id, background)
    return await asyncio.to_thread(_snapshot_sync, workflow_id, user_id)


async def cancel_workflow(user_id: UUID, workflow_id: UUID) -> WorkflowResponse:
    await asyncio.to_thread(_cancel_sync, workflow_id, user_id)
    return await asyncio.to_thread(_snapshot_sync, workflow_id, user_id)


async def get_workflow(user_id: UUID, workflow_id: UUID) -> WorkflowResponse:
    return await asyncio.to_thread(_snapshot_sync, workflow_id, user_id)


async def list_workflows(user_id: UUID) -> list[WorkflowSummaryResponse]:
    return await asyncio.to_thread(_list_sync, user_id)


# Register this capability in the kernel's workflow catalog (drives the
# /api/ai/capabilities listing; override=True keeps re-imports idempotent).
workflow_registry.register(
    "assessment",
    WorkflowDefinition(
        kind="assessment",
        title="Assessment Intelligence",
        stage_keys=tuple(s.value for s in stage_registry.registered_pipeline()),
        description="Plan an assessment through staged analysis with human approval checkpoints",
        allowed_roles=(UserRole.TEACHER.value,),
    ),
    override=True,
)
