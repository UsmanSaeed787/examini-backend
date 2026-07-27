"""ContextEngine: orchestrates facet providers into one immutable
AgentExecutionContext.

Failure-safe by contract: a provider error becomes a warning on the context,
never an exception out of build() — context collection must never kill a
run. Extensible by contract: future capabilities (Student Success, Career
Intelligence, …) register additional providers; the engine and existing
consumers do not change."""
import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional, Sequence, Tuple
from uuid import UUID, uuid4

from app.ai.context import AIRunContext
from app.ai.context_engine.models import (
    AgentExecutionContext,
    KnowledgeReference,
    WorkflowFacet,
)
from app.ai.context_engine.providers import ContextProvider, default_providers


@dataclass(frozen=True)
class ContextRequest:
    """What the engine needs to know to collect. Optional ids simply switch
    their facets off (no workflow_id -> no workflow/stage/artifact facets)."""

    user_id: UUID
    role: str
    agent_key: Optional[str] = None
    session_id: Optional[str] = None
    workflow_id: Optional[UUID] = None
    stage_key: Optional[str] = None
    class_id: Optional[UUID] = None
    request_id: str = ""


def _compose_knowledge(facets: dict) -> Tuple[KnowledgeReference, ...]:
    """Cross-facet composition: everything an agent could consult via its
    tools, expressed as references (payloads stay behind authz'd tools)."""
    refs: List[KnowledgeReference] = []
    course = facets.get("course")
    if course:
        refs.extend(
            KnowledgeReference(
                kind="material", ref_id=str(m.material_id), title=m.title, source="course"
            )
            for m in course.materials
        )
    workflow_facet: Optional[WorkflowFacet] = facets.get("workflow")
    if workflow_facet:
        refs.extend(
            KnowledgeReference(
                kind="artifact",
                ref_id=f"{workflow_facet.workflow.workflow_id}:{a.stage_key}",
                title=f"{a.stage_key} artifact (rev {a.revision})",
                source="workflow",
            )
            for a in workflow_facet.artifacts
        )
    for run in facets.get("previous_outputs") or ():
        refs.append(
            KnowledgeReference(
                kind="run", ref_id=str(run.run_id), title=f"previous {run.agent_key} run", source="history"
            )
        )
    return tuple(refs)


class ContextEngine:
    def __init__(self, providers: Optional[Sequence[ContextProvider]] = None):
        self._providers: List[ContextProvider] = list(providers if providers is not None else default_providers())

    def register_provider(self, provider: ContextProvider) -> None:
        """Extension point: replaces a provider with the same facet name,
        otherwise appends."""
        self._providers = [p for p in self._providers if p.facet != provider.facet]
        self._providers.append(provider)

    async def build(self, request: ContextRequest) -> AgentExecutionContext:
        def _collect_all() -> tuple[dict, list[str]]:
            facets: dict = {}
            warnings: list[str] = []
            for provider in self._providers:
                try:
                    facets[provider.facet] = provider.collect(request)
                except Exception as exc:  # noqa: BLE001 — facet failure is a warning, not a crash
                    warnings.append(f"{provider.facet}: {exc.__class__.__name__}")
                    facets[provider.facet] = None
            return facets, warnings

        facets, warnings = await asyncio.to_thread(_collect_all)
        workflow_facet: Optional[WorkflowFacet] = facets.get("workflow")
        return AgentExecutionContext(
            request_id=request.request_id or uuid4().hex,
            built_at=datetime.now(timezone.utc),
            agent_key=request.agent_key,
            user=facets.get("user"),
            permissions=facets.get("permissions"),
            workflow=workflow_facet.workflow if workflow_facet else None,
            stage=workflow_facet.stage if workflow_facet else None,
            artifacts=workflow_facet.artifacts if workflow_facet else (),
            conversation=facets.get("conversation"),
            institution=facets.get("institution"),
            policies=facets.get("policies"),
            course=facets.get("course"),
            previous_outputs=facets.get("previous_outputs") or (),
            memories=facets.get("memories") or (),
            knowledge=_compose_knowledge(facets),
            warnings=tuple(warnings),
        )


_default_engine = ContextEngine()


def register_provider(provider: ContextProvider) -> None:
    _default_engine.register_provider(provider)


async def build_context(request: ContextRequest) -> AgentExecutionContext:
    return await _default_engine.build(request)


def _uuid_or_none(value) -> Optional[UUID]:
    if value is None:
        return None
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


async def build_for_identity(
    identity: AIRunContext,
    agent_key: Optional[str] = None,
    session_id: Optional[str] = None,
) -> AgentExecutionContext:
    """Convenience bridge used by the runner: derives the ContextRequest from
    the run identity, picking up workflow/stage/class hints callers place in
    AIRunContext.extra (the facade sets class_id; AgentStageHandler sets
    workflow_id and stage)."""
    extra = identity.extra or {}
    request = ContextRequest(
        user_id=identity.user_id,
        role=identity.role,
        agent_key=agent_key or identity.agent_key,
        session_id=session_id,
        workflow_id=_uuid_or_none(extra.get("workflow_id")),
        stage_key=extra.get("stage") or extra.get("stage_key"),
        class_id=_uuid_or_none(extra.get("class_id")),
        request_id=identity.request_id,
    )
    return await build_context(request)
