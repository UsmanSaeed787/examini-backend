"""Workflow read tools — how specialist agents (and the assistants) see
workflow state and upstream artifacts without touching persistence.

Two tool keys share one authz capability ('workflow.read')."""
from uuid import UUID

from pydantic import BaseModel, Field

from app.ai.tools.registry import ToolContext, tool
from app.ai.workflows.assessment.persistence import AIWorkflow, AIWorkflowStage
from app.middleware.error_handler import NotFoundError


class GetWorkflowParams(BaseModel):
    workflow_id: str = Field(description="Assessment workflow id (UUID)")


class GetStageArtifactParams(BaseModel):
    workflow_id: str = Field(description="Assessment workflow id (UUID)")
    stage_key: str = Field(description="Stage key, e.g. curriculum_analysis")


@tool(
    key="workflow.get_assessment_workflow",
    description="Get the state of one of the calling user's assessment workflows "
    "(stages, statuses, current position).",
    permission="workflow.read",
    params=GetWorkflowParams,
    services=("assessment workflow store",),
    tags=("workflow", "read"),
)
def get_assessment_workflow(ctx: ToolContext, params: GetWorkflowParams) -> dict:
    with ctx.db() as db:
        workflow = (
            db.query(AIWorkflow)
            .filter(
                AIWorkflow.id == UUID(params.workflow_id),
                AIWorkflow.user_id == ctx.identity.user_id,
            )
            .first()
        )
        if not workflow:
            raise NotFoundError("Workflow not found")
        stage_rows = (
            db.query(AIWorkflowStage)
            .filter(AIWorkflowStage.workflow_id == workflow.id)
            .order_by(AIWorkflowStage.sequence)
            .all()
        )
        return {
            "id": str(workflow.id),
            "title": workflow.title,
            "state": workflow.state,
            "current_stage": workflow.current_stage,
            "config": dict(workflow.config or {}),
            "stages": [
                {"stage_key": s.stage_key, "status": s.status, "revision": s.revision}
                for s in stage_rows
            ],
        }


@tool(
    key="workflow.get_stage_artifact",
    description="Get the produced artifact of a specific stage of one of the calling "
    "user's assessment workflows (e.g. the curriculum outline or blueprint).",
    permission="workflow.read",
    params=GetStageArtifactParams,
    services=("assessment workflow store",),
    tags=("workflow", "read"),
)
def get_stage_artifact(ctx: ToolContext, params: GetStageArtifactParams) -> dict:
    with ctx.db() as db:
        row = (
            db.query(AIWorkflowStage)
            .join(AIWorkflow, AIWorkflowStage.workflow_id == AIWorkflow.id)
            .filter(
                AIWorkflow.id == UUID(params.workflow_id),
                AIWorkflow.user_id == ctx.identity.user_id,
                AIWorkflowStage.stage_key == params.stage_key,
            )
            .first()
        )
        if not row:
            raise NotFoundError("Workflow stage not found")
        return {
            "stage_key": row.stage_key,
            "status": row.status,
            "revision": row.revision,
            "notes": row.notes,
            "artifact": row.artifact,
        }
