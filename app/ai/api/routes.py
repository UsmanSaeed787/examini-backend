"""Thin /api/ai surface (mounted in app/main.py). Delegates entirely to the
runtime; SDK imports stay inside the runner so this module is cheap to load."""
import asyncio
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.ai.api.deps import admin_context, build_context, require_ai_enabled
from app.ai.config import ai_settings
from app.ai.context import AIRunContext
from app.ai.jobs import background, inline
from app.ai.persistence import store
from app.ai.schemas.requests import CreateRunRequest
from app.ai.schemas.responses import (
    AgentInfoResponse,
    CapabilitiesResponse,
    CapabilityResponse,
    RunResponse,
    ToolInfoResponse,
    UsageInfo,
    WorkflowCapabilityResponse,
)
from app.ai.workflows.assessment.api import router as assessment_workflow_router
from app.middleware.error_handler import NotFoundError

router = APIRouter()
router.include_router(
    assessment_workflow_router,
    prefix="/workflows/assessment",
    tags=["AI Workflows"],
)


def _serialize_output(final_output):
    if final_output is None:
        return None
    if isinstance(final_output, BaseModel):
        return final_output.model_dump(mode="json")
    return str(final_output)


@router.get("/capabilities", response_model=CapabilitiesResponse)
async def list_capabilities(context: AIRunContext = Depends(build_context)):
    """List the agents the calling user's role may invoke via /runs."""
    from app.ai.agents.registry import list_for_role
    from app.ai.runtime.registry import workflow_registry

    if not ai_settings.enabled:
        return CapabilitiesResponse(enabled=False, agents=[], workflows=[])
    agents = [
        CapabilityResponse(
            agent_key=spec.key, description=spec.description, uses_session=spec.uses_session
        )
        for spec in list_for_role(context.role)
    ]
    workflows = [
        WorkflowCapabilityResponse(
            kind=definition.kind,
            title=definition.title,
            description=definition.description,
            stage_keys=list(definition.stage_keys),
        )
        for _, definition in workflow_registry.items()
        if not definition.allowed_roles or context.role in definition.allowed_roles
    ]
    return CapabilitiesResponse(enabled=True, agents=agents, workflows=workflows)


@router.post("/runs", response_model=RunResponse)
async def create_run(
    payload: CreateRunRequest,
    context: AIRunContext = Depends(build_context),
    _: None = Depends(require_ai_enabled),
):
    """Execute an agent run (inline by default; background=true to poll)."""
    from app.ai.agents.registry import ensure_agent_allowed

    spec = ensure_agent_allowed(payload.agent_key, context.role, version=payload.agent_version)
    if not spec.api_invocable:
        raise NotFoundError(f"Agent '{payload.agent_key}' is not invocable via this endpoint")

    if payload.background:
        run_id = await background.submit(
            context, payload.agent_key, payload.input, payload.session_id, payload.agent_version
        )
        return RunResponse(
            run_id=run_id, agent_key=payload.agent_key, status="queued", session_id=payload.session_id
        )

    outcome = await inline.submit(
        context, payload.agent_key, payload.input, payload.session_id, payload.agent_version
    )
    return RunResponse(
        run_id=outcome.run_id,
        agent_key=outcome.agent_key,
        status=outcome.status,
        output=_serialize_output(outcome.final_output),
        session_id=outcome.session_id,
        usage=UsageInfo(**outcome.usage) if outcome.usage else None,
    )


# ---------------------------------------------------------------- tool admin

@router.get("/tools", response_model=list[ToolInfoResponse])
async def list_tools(context: AIRunContext = Depends(admin_context)):
    """Full Tool Registry metadata: keys, permissions, role coverage, wrapped
    services, and the exact JSON schema each tool exposes to the model
    (admin only)."""
    from app.ai.tools.registry import list_all as list_all_tools

    return [ToolInfoResponse(**entry) for entry in await asyncio.to_thread(list_all_tools)]


# ---------------------------------------------------------------- agent admin

@router.get("/agents", response_model=list[AgentInfoResponse])
async def list_agents(context: AIRunContext = Depends(admin_context)):
    """Full registry metadata for every agent, including disabled ones
    (admin only)."""
    from app.ai.agents.registry import list_all

    return [AgentInfoResponse(**entry) for entry in await asyncio.to_thread(list_all)]


@router.post("/agents/{agent_key}/enable")
async def enable_agent(agent_key: str, context: AIRunContext = Depends(admin_context)):
    """Enable an agent (admin only; shared across workers via ai_agent_state)."""
    from app.ai.agents.registry import set_enabled

    await asyncio.to_thread(set_enabled, agent_key, True, context.user_id)
    return {"message": f"Agent '{agent_key}' enabled"}


@router.post("/agents/{agent_key}/disable")
async def disable_agent(agent_key: str, context: AIRunContext = Depends(admin_context)):
    """Disable an agent (admin only). Running executions finish; new runs
    are rejected with AI_AGENT_DISABLED."""
    from app.ai.agents.registry import set_enabled

    await asyncio.to_thread(set_enabled, agent_key, False, context.user_id)
    return {"message": f"Agent '{agent_key}' disabled"}


@router.post("/runs/{run_id}/cancel")
async def cancel_run(
    run_id: UUID,
    context: AIRunContext = Depends(build_context),
    _: None = Depends(require_ai_enabled),
):
    """Cancel an in-flight run (must belong to the caller and still be
    executing in this process)."""
    from app.ai.runtime.runner import cancel_run as signal_cancel

    record = await asyncio.to_thread(store.get_run, run_id, context.user_id)
    if not record:
        raise NotFoundError("Run not found")
    if not signal_cancel(run_id):
        raise NotFoundError("Run is not currently executing")
    return {"message": "Cancellation requested"}


@router.get("/runs/{run_id}", response_model=RunResponse)
async def get_run(
    run_id: UUID,
    context: AIRunContext = Depends(build_context),
    _: None = Depends(require_ai_enabled),
):
    """Fetch one of the calling user's runs (used to poll background runs)."""
    record = await asyncio.to_thread(store.get_run, run_id, context.user_id)
    if not record:
        raise NotFoundError("Run not found")
    return RunResponse(
        run_id=record["run_id"],
        agent_key=record["agent_key"],
        status=record["status"],
        output=record["output_summary"],
        session_id=record["session_id"],
        usage=UsageInfo(**record["usage"]) if record["usage"] else None,
        error_code=record["error_code"],
        error_message=record["error_message"],
        created_at=record["created_at"],
        finished_at=record["finished_at"],
    )
