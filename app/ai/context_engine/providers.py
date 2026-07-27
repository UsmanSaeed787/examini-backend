"""Facet providers — each collects ONE slice of the execution context.

Providers are synchronous (the engine runs them off the event loop in a
single worker-thread pass), read-only, and sourced from real platform state:
existing tables, the authz matrix, the registries, and app settings. Nothing
is invented and no business logic is duplicated — the grading policy, for
example, is DERIVED by probing the platform's own calculate_grade()."""
from typing import Optional, Protocol

from app.ai.context_engine.models import (
    AcademicPolicies,
    ArtifactRef,
    ConversationContext,
    ConversationMessage,
    CourseContext,
    GradeBand,
    InstitutionContext,
    MaterialRef,
    MemoryItem,
    PermissionsContext,
    RunSummary,
    SectionRef,
    StageInfo,
    UserContext,
    WorkflowContext,
    WorkflowFacet,
    freeze_mapping,
)

_PARSEABLE_TYPES = {"pdf", "docx", "txt"}


class ContextProvider(Protocol):
    """One facet collector. `facet` names the AgentExecutionContext field
    family it feeds; collect() returns that facet's model or None."""

    facet: str

    def collect(self, request) -> object: ...


class UserProvider:
    facet = "user"

    def collect(self, request) -> Optional[UserContext]:
        from app.ai.tools._base import db_session
        from app.models.user import User

        with db_session() as db:
            user = db.query(User).filter(User.id == request.user_id).first()
            if not user:
                return None
            return UserContext(
                user_id=user.id, email=user.email, role=user.role, full_name=user.full_name
            )


class PermissionsProvider:
    facet = "permissions"

    def collect(self, request) -> PermissionsContext:
        from app.ai.agents.registry import list_for_role
        from app.ai.policies.authz import TOOL_CAPABILITIES

        return PermissionsContext(
            role=request.role,
            allowed_tools=tuple(sorted(TOOL_CAPABILITIES.get(request.role, frozenset()))),
            allowed_agents=tuple(d.key for d in list_for_role(request.role, api_only=False)),
        )


class WorkflowProvider:
    facet = "workflow"

    def collect(self, request) -> Optional[WorkflowFacet]:
        if request.workflow_id is None:
            return None
        from app.ai.tools._base import db_session
        from app.ai.workflows.assessment.persistence import AIWorkflow, AIWorkflowStage

        with db_session() as db:
            workflow = (
                db.query(AIWorkflow)
                .filter(AIWorkflow.id == request.workflow_id, AIWorkflow.user_id == request.user_id)
                .first()
            )
            if not workflow:
                return None
            stage_rows = (
                db.query(AIWorkflowStage)
                .filter(AIWorkflowStage.workflow_id == workflow.id)
                .order_by(AIWorkflowStage.sequence)
                .all()
            )
        stage = None
        for row in stage_rows:
            if request.stage_key and row.stage_key == request.stage_key:
                stage = StageInfo(
                    stage_key=row.stage_key,
                    sequence=row.sequence,
                    status=row.status,
                    revision=row.revision,
                    notes=row.notes,
                )
        artifacts = tuple(
            ArtifactRef(
                stage_key=row.stage_key,
                status=row.status,
                revision=row.revision,
                artifact=freeze_mapping(row.artifact),
            )
            for row in stage_rows
            if row.artifact is not None
        )
        return WorkflowFacet(
            workflow=WorkflowContext(
                workflow_id=workflow.id,
                kind=workflow.kind,
                title=workflow.title,
                state=workflow.state,
                approval_mode=workflow.approval_mode,
                current_stage=workflow.current_stage,
                config=freeze_mapping(workflow.config),
            ),
            stage=stage,
            artifacts=artifacts,
        )


class ConversationProvider:
    facet = "conversation"

    def collect(self, request) -> Optional[ConversationContext]:
        if not request.session_id:
            return None
        from app.ai.config import ai_settings
        from app.ai.persistence import store

        items = store.get_session_items(request.session_id, ai_settings.context_history_limit)
        messages = []
        for item in items:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or item.get("type") or "unknown")
            content = item.get("content")
            if isinstance(content, list):  # SDK content-part lists
                content = " ".join(
                    str(part.get("text", "")) for part in content if isinstance(part, dict)
                )
            if content is None:
                continue
            messages.append(ConversationMessage(role=role, content=str(content)[:2000]))
        return ConversationContext(session_id=request.session_id, messages=tuple(messages))


class InstitutionProvider:
    facet = "institution"

    def collect(self, request) -> InstitutionContext:
        from app.config import settings

        return InstitutionContext(
            name=settings.app_name,
            platform_version=settings.app_version,
            debug=bool(settings.debug),
        )


class AcademicPolicyProvider:
    facet = "policies"

    def collect(self, request) -> AcademicPolicies:
        from app.ai.config import ai_settings
        from app.config import settings
        from app.utils.helpers import calculate_grade

        # Derive the grading ladder from the platform's own function —
        # single source of truth, nothing re-declared here.
        thresholds = (90.0, 80.0, 70.0, 60.0, 50.0, 0.0)
        bands = tuple(GradeBand(min_percentage=t, grade=calculate_grade(t)[0]) for t in thresholds)
        passing = [t for t in thresholds if calculate_grade(t)[1]]
        return AcademicPolicies(
            grade_bands=bands,
            pass_threshold=min(passing) if passing else 0.0,
            max_questions_per_exam=ai_settings.max_questions_per_exam,
            allowed_material_types=tuple(settings.allowed_file_types_list),
            max_file_size_mb=settings.max_file_size_mb,
        )


class CourseProvider:
    facet = "course"

    def collect(self, request) -> Optional[CourseContext]:
        if request.class_id is None:
            return None
        from app.ai.tools._base import db_session
        from app.models.class_model import Class, Section
        from app.models.material import Material

        with db_session() as db:
            cls = db.query(Class).filter(Class.id == request.class_id).first()
            if not cls:
                return None
            sections = (
                db.query(Section).filter(Section.class_id == cls.id).order_by(Section.name).all()
            )
            materials_query = db.query(Material).filter(
                Material.class_id == cls.id, Material.is_active == True  # noqa: E712
            )
            if request.role == "teacher":
                materials_query = materials_query.filter(Material.teacher_id == request.user_id)
            materials = materials_query.order_by(Material.uploaded_at.desc()).limit(50).all()
        return CourseContext(
            class_id=cls.id,
            name=cls.name,
            description=cls.description,
            sections=tuple(SectionRef(section_id=s.id, name=s.name) for s in sections),
            materials=tuple(
                MaterialRef(
                    material_id=m.id,
                    title=m.title,
                    file_type=m.file_type,
                    parseable=(m.file_type or "").lower() in _PARSEABLE_TYPES,
                )
                for m in materials
            ),
        )


class AgentMemoryProvider:
    """Memory Layer facet: the calling user's agent-scope memories for the
    executing agent, surfaced read-only into the snapshot."""

    facet = "memories"

    def collect(self, request) -> tuple:
        if not request.agent_key:
            return ()
        from app.ai.memory.service import memory_service

        records = memory_service.recall_agent(
            user_id=request.user_id, agent_key=request.agent_key, limit=10
        )
        return tuple(
            MemoryItem(
                scope=r.scope.value,
                key=r.key,
                content=r.content,
                created_at=r.created_at,
            )
            for r in records
        )


class PreviousOutputsProvider:
    facet = "previous_outputs"

    def collect(self, request) -> tuple:
        from app.ai.config import ai_settings
        from app.ai.persistence.models import AIRun
        from app.ai.tools._base import db_session

        with db_session() as db:
            query = (
                db.query(AIRun)
                .filter(AIRun.user_id == request.user_id, AIRun.status == "completed")
            )
            if request.agent_key:
                query = query.filter(AIRun.agent_key == request.agent_key)
            rows = (
                query.order_by(AIRun.finished_at.desc())
                .limit(ai_settings.context_previous_runs_limit)
                .all()
            )
        return tuple(
            RunSummary(
                run_id=row.id,
                agent_key=row.agent_key,
                status=row.status,
                output_summary=row.output_summary,
                finished_at=row.finished_at,
            )
            for row in rows
        )


def default_providers() -> tuple:
    return (
        UserProvider(),
        PermissionsProvider(),
        WorkflowProvider(),
        ConversationProvider(),
        InstitutionProvider(),
        AcademicPolicyProvider(),
        CourseProvider(),
        PreviousOutputsProvider(),
        AgentMemoryProvider(),
    )
