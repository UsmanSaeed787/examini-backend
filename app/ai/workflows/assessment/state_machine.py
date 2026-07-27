"""Pure transition rules for workflows and stages. No I/O — fully unit-testable.

The orchestrator (service.py) must route every state change through
ensure_workflow_transition / ensure_stage_transition; an illegal transition
is a ValidationError (422), never silent corruption."""
from app.ai.workflows.assessment.domain import (
    GENERATION_TRANSITIONS,
    ApprovalMode,
    GenerationStatus,
    StageKey,
    StageStatus,
    WorkflowState,
)
from app.middleware.error_handler import ValidationError

WORKFLOW_TRANSITIONS: dict[WorkflowState, frozenset[WorkflowState]] = {
    WorkflowState.DRAFT: frozenset({WorkflowState.IN_PROGRESS, WorkflowState.CANCELLED}),
    WorkflowState.IN_PROGRESS: frozenset(
        {
            WorkflowState.IN_PROGRESS,       # advancing to the next stage
            WorkflowState.AWAITING_APPROVAL,
            WorkflowState.COMPLETED,
            WorkflowState.CANCELLED,
            WorkflowState.FAILED,
        }
    ),
    WorkflowState.AWAITING_APPROVAL: frozenset(
        {WorkflowState.IN_PROGRESS, WorkflowState.COMPLETED, WorkflowState.CANCELLED}
    ),
    WorkflowState.COMPLETED: frozenset(),
    WorkflowState.CANCELLED: frozenset(),
    WorkflowState.FAILED: frozenset(),
}

STAGE_TRANSITIONS: dict[StageStatus, frozenset[StageStatus]] = {
    StageStatus.PENDING: frozenset({StageStatus.RUNNING}),
    StageStatus.RUNNING: frozenset(
        {StageStatus.IN_REVIEW, StageStatus.APPROVED, StageStatus.FAILED}
    ),
    StageStatus.IN_REVIEW: frozenset({StageStatus.APPROVED, StageStatus.REJECTED}),
    StageStatus.REJECTED: frozenset({StageStatus.PENDING}),
    StageStatus.APPROVED: frozenset(),
    StageStatus.FAILED: frozenset({StageStatus.PENDING}),  # allow retry after fix
}


def ensure_workflow_transition(current: WorkflowState, target: WorkflowState) -> None:
    if target not in WORKFLOW_TRANSITIONS[current]:
        raise ValidationError(
            f"Illegal workflow transition: {current.value} -> {target.value}"
        )


def ensure_stage_transition(current: StageStatus, target: StageStatus) -> None:
    if target not in STAGE_TRANSITIONS[current]:
        raise ValidationError(
            f"Illegal stage transition: {current.value} -> {target.value}"
        )


def ensure_stage_invalidation(current: StageStatus) -> None:
    """Guard for re-opening a settled stage because its INPUTS changed.

    Deliberately separate from ensure_stage_transition, which stays strict:
    within a normal pipeline run an approved stage can never be un-approved.
    Invalidation is a different, audited operation — the teacher edited the
    question mix, so the blueprint and everything derived from it no longer
    describes what was agreed and must be recomputed."""
    if current == StageStatus.RUNNING:
        raise ValidationError(
            "Cannot change the question mix while a step is still running"
        )


def ensure_generation_transition(
    current: GenerationStatus, target: GenerationStatus
) -> None:
    """Guard for the materialization lifecycle. Notably: PUBLISHED is
    terminal (a released exam is never silently regenerated over), and
    GENERATED is the only status PUBLISHED can be reached from."""
    if target not in GENERATION_TRANSITIONS[current]:
        raise ValidationError(
            f"Illegal generation transition: {current.value} -> {target.value}"
        )


def checkpoint_required(
    mode: ApprovalMode, stage: StageKey, pipeline: tuple[StageKey, ...]
) -> bool:
    """Does this stage stop for a human approval checkpoint?"""
    if mode == ApprovalMode.NONE:
        return False
    if mode == ApprovalMode.FINAL_ONLY:
        return stage == pipeline[-1]
    return True  # EVERY_STAGE


def next_stage(
    current: StageKey, pipeline: tuple[StageKey, ...]
) -> StageKey | None:
    idx = pipeline.index(current)
    return pipeline[idx + 1] if idx + 1 < len(pipeline) else None
