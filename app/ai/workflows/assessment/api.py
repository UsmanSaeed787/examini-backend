"""HTTP surface for the Assessment Intelligence workflow.

Mounted by ai/api/routes.py under /api/ai/workflows/assessment. Teacher-only
(workflows are owned rows; every service call is scoped by user_id)."""
from uuid import UUID

from fastapi import APIRouter, Depends

from app.ai.api.deps import build_context, require_ai_enabled
from app.ai.context import AIRunContext
from app.ai.workflows.assessment import materialization, service
from app.ai.workflows.assessment.domain import StageKey
from app.ai.workflows.assessment.schemas import (
    AdjustMixRequest,
    ApproveRequest,
    CreateWorkflowRequest,
    GenerationHistoryResponse,
    GenerationResponse,
    PublishRequest,
    RejectRequest,
    WorkflowResponse,
    WorkflowSummaryResponse,
)
from app.middleware.error_handler import AuthorizationError
from app.utils.constants import UserRole

router = APIRouter()


def teacher_context(
    context: AIRunContext = Depends(build_context),
    _: None = Depends(require_ai_enabled),
) -> AIRunContext:
    if context.role != UserRole.TEACHER.value:
        raise AuthorizationError("Teacher access required")
    return context


@router.post("", response_model=WorkflowResponse)
async def create_workflow(
    payload: CreateWorkflowRequest, context: AIRunContext = Depends(teacher_context)
):
    """Create a workflow in DRAFT (nothing runs until /start)."""
    return await service.create_workflow(context.user_id, payload)


@router.get("", response_model=list[WorkflowSummaryResponse])
async def list_workflows(context: AIRunContext = Depends(teacher_context)):
    """List the calling teacher's assessment workflows."""
    return await service.list_workflows(context.user_id)


@router.get("/{workflow_id}", response_model=WorkflowResponse)
async def get_workflow(workflow_id: UUID, context: AIRunContext = Depends(teacher_context)):
    """Full workflow state: stages, artifacts, pending checkpoint, result."""
    return await service.get_workflow(context.user_id, workflow_id)


@router.post("/{workflow_id}/start", response_model=WorkflowResponse)
async def start_workflow(workflow_id: UUID, context: AIRunContext = Depends(teacher_context)):
    """Start the pipeline; runs until the first human checkpoint (or completion)."""
    return await service.start_workflow(context.user_id, workflow_id)


@router.post("/{workflow_id}/stages/{stage_key}/approve", response_model=WorkflowResponse)
async def approve_stage(
    workflow_id: UUID,
    stage_key: StageKey,
    payload: ApproveRequest,
    context: AIRunContext = Depends(teacher_context),
):
    """Approve the stage under review; the pipeline advances automatically."""
    return await service.approve_stage(context.user_id, workflow_id, stage_key, payload.notes)


@router.post("/{workflow_id}/stages/{stage_key}/reject", response_model=WorkflowResponse)
async def reject_stage(
    workflow_id: UUID,
    stage_key: StageKey,
    payload: RejectRequest,
    context: AIRunContext = Depends(teacher_context),
):
    """Reject with notes (and optional config corrections); the stage re-runs
    as a new revision."""
    return await service.reject_stage(
        context.user_id, workflow_id, stage_key, payload.notes, payload.config_patch
    )


@router.post("/{workflow_id}/adjust", response_model=WorkflowResponse)
async def adjust_question_mix(
    workflow_id: UUID,
    payload: AdjustMixRequest,
    context: AIRunContext = Depends(teacher_context),
):
    """Change the question mix and recompute, without a model call.

    Use this for "make it 8 questions, not 6". Use reject for "this misses the
    lab component" — that one needs the AI to think again. Everything derived
    from the mix (blueprint, quality, difficulty, scheduling) is recomputed
    deterministically; the curriculum analysis is untouched because the
    materials did not change."""
    return await service.adjust_question_mix(
        context.user_id, workflow_id, payload.question_config
    )


@router.post("/{workflow_id}/cancel", response_model=WorkflowResponse)
async def cancel_workflow(workflow_id: UUID, context: AIRunContext = Depends(teacher_context)):
    """Cancel a non-terminal workflow."""
    return await service.cancel_workflow(context.user_id, workflow_id)


# ---------------------------------------------------------------- materialization

@router.post("/{workflow_id}/generate", response_model=GenerationResponse)
async def generate_assessment(
    workflow_id: UUID, context: AIRunContext = Depends(teacher_context)
):
    """Generate the questions for a completed workflow's approved plan.

    Produces an UNPUBLISHED draft exam — students cannot see it until the
    teacher calls /publish. Re-invoking supersedes an earlier draft (the old
    draft exam is left in place; delete it through the exam endpoints)."""
    return await materialization.generate_assessment(context.user_id, workflow_id)


@router.get("/{workflow_id}/generation", response_model=GenerationResponse)
async def get_generation(
    workflow_id: UUID, context: AIRunContext = Depends(teacher_context)
):
    """Current materialization state: status, exam id, question count, and any
    validation findings the teacher must acknowledge before publishing."""
    return await materialization.get_generation(context.user_id, workflow_id)


@router.get("/{workflow_id}/generations", response_model=GenerationHistoryResponse)
async def get_generation_history(
    workflow_id: UUID, context: AIRunContext = Depends(teacher_context)
):
    """Audit trail of every materialization attempt, newest first."""
    return await materialization.get_generation_history(context.user_id, workflow_id)


@router.post("/{workflow_id}/publish", response_model=GenerationResponse)
async def publish_assessment(
    workflow_id: UUID,
    payload: PublishRequest,
    context: AIRunContext = Depends(teacher_context),
):
    """Release the generated exam to students.

    The only endpoint in the assessment pipeline that makes an exam visible,
    and it is always an explicit human decision — no stage, handler, or agent
    can reach it."""
    return await materialization.publish_assessment(
        context.user_id, workflow_id, payload.acknowledge_findings
    )
