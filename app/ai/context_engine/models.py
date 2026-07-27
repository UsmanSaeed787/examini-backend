"""Strongly typed, immutable context models.

Every model is a frozen dataclass; collections are tuples and dict-shaped
data is wrapped in MappingProxyType by the engine — consumers can read
everything and mutate nothing. Facets are Optional on the top-level object:
a facet is None when its source was not applicable (e.g. no workflow) or its
provider failed (recorded in `warnings`)."""
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Any, Mapping, Optional, Tuple
from uuid import UUID

EMPTY_MAPPING: Mapping[str, Any] = MappingProxyType({})


def freeze_mapping(data: Optional[dict]) -> Mapping[str, Any]:
    return MappingProxyType(dict(data)) if data else EMPTY_MAPPING


# ---------------------------------------------------------------- identity

@dataclass(frozen=True)
class UserContext:
    user_id: UUID
    email: str
    role: str
    full_name: Optional[str] = None


@dataclass(frozen=True)
class PermissionsContext:
    role: str
    allowed_tools: Tuple[str, ...] = ()
    allowed_agents: Tuple[str, ...] = ()


# ---------------------------------------------------------------- workflow

@dataclass(frozen=True)
class WorkflowContext:
    workflow_id: UUID
    kind: str
    title: str
    state: str
    approval_mode: str
    current_stage: Optional[str] = None
    config: Mapping[str, Any] = EMPTY_MAPPING


@dataclass(frozen=True)
class StageInfo:
    stage_key: str
    sequence: int
    status: str
    revision: int
    notes: Optional[str] = None


@dataclass(frozen=True)
class ArtifactRef:
    stage_key: str
    status: str
    revision: int
    artifact: Mapping[str, Any] = EMPTY_MAPPING


@dataclass(frozen=True)
class WorkflowFacet:
    """Composite returned by the workflow provider."""

    workflow: WorkflowContext
    stage: Optional[StageInfo] = None
    artifacts: Tuple[ArtifactRef, ...] = ()


# ---------------------------------------------------------------- conversation

@dataclass(frozen=True)
class ConversationMessage:
    role: str
    content: str


@dataclass(frozen=True)
class ConversationContext:
    session_id: str
    messages: Tuple[ConversationMessage, ...] = ()


# ---------------------------------------------------------------- institution

@dataclass(frozen=True)
class InstitutionContext:
    name: str
    platform_version: str
    debug: bool = False


@dataclass(frozen=True)
class GradeBand:
    min_percentage: float
    grade: str


@dataclass(frozen=True)
class AcademicPolicies:
    grade_bands: Tuple[GradeBand, ...] = ()
    pass_threshold: float = 50.0
    max_questions_per_exam: int = 100
    allowed_material_types: Tuple[str, ...] = ()
    max_file_size_mb: int = 50


# ---------------------------------------------------------------- course

@dataclass(frozen=True)
class SectionRef:
    section_id: UUID
    name: str


@dataclass(frozen=True)
class MaterialRef:
    material_id: UUID
    title: str
    file_type: Optional[str] = None
    parseable: bool = False


@dataclass(frozen=True)
class CourseContext:
    class_id: UUID
    name: str
    description: Optional[str] = None
    sections: Tuple[SectionRef, ...] = ()
    materials: Tuple[MaterialRef, ...] = ()


# ---------------------------------------------------------------- history

@dataclass(frozen=True)
class RunSummary:
    run_id: UUID
    agent_key: str
    status: str
    output_summary: Optional[str] = None
    finished_at: Optional[datetime] = None


@dataclass(frozen=True)
class MemoryItem:
    """A recalled memory surfaced into the execution context (agent-scope
    facts collected by the Memory Layer's context provider)."""

    scope: str
    key: Optional[str]
    content: Mapping[str, Any] = EMPTY_MAPPING
    created_at: Optional[datetime] = None


@dataclass(frozen=True)
class KnowledgeReference:
    """A pointer to something an agent may consult via its tools — never the
    payload itself (tools fetch on demand, under authz)."""

    kind: str      # "material" | "artifact" | "run"
    ref_id: str
    title: str
    source: str    # e.g. "course", "workflow", "history"


# ---------------------------------------------------------------- top level

@dataclass(frozen=True)
class AgentExecutionContext:
    """The one immutable object every agent run receives (attached to
    AIRunContext.snapshot). Consumers: tools, guardrails, and future
    context-aware instructions."""

    request_id: str
    built_at: datetime
    agent_key: Optional[str]
    user: Optional[UserContext] = None
    permissions: Optional[PermissionsContext] = None
    workflow: Optional[WorkflowContext] = None
    stage: Optional[StageInfo] = None
    artifacts: Tuple[ArtifactRef, ...] = ()
    conversation: Optional[ConversationContext] = None
    institution: Optional[InstitutionContext] = None
    policies: Optional[AcademicPolicies] = None
    course: Optional[CourseContext] = None
    previous_outputs: Tuple[RunSummary, ...] = ()
    memories: Tuple[MemoryItem, ...] = ()
    knowledge: Tuple[KnowledgeReference, ...] = ()
    warnings: Tuple[str, ...] = field(default_factory=tuple)
