"""Response DTOs for the /api/ai surface."""
from datetime import datetime
from typing import Any, List, Optional
from uuid import UUID

from pydantic import BaseModel


class UsageInfo(BaseModel):
    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


class RunResponse(BaseModel):
    run_id: UUID
    agent_key: str
    status: str  # queued|running|completed|failed
    output: Optional[Any] = None
    session_id: Optional[str] = None
    usage: Optional[UsageInfo] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    created_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


class CapabilityResponse(BaseModel):
    agent_key: str
    description: str
    uses_session: bool


class ModelOverridesInfo(BaseModel):
    model: Optional[str] = None
    max_turns: Optional[int] = None
    max_output_tokens: Optional[int] = None
    temperature: Optional[float] = None


class AgentInfoResponse(BaseModel):
    """Full registry metadata for one agent (admin surface)."""

    key: str
    name: str
    description: str
    version: str
    versions: List[str] = []
    allowed_roles: List[str] = []
    capabilities: List[str] = []
    required_tools: List[str] = []
    supported_workflows: List[str] = []
    structured_output: Optional[str] = None
    uses_session: bool = False
    api_invocable: bool = True
    enabled: bool = True
    model_overrides: Optional[ModelOverridesInfo] = None


class ToolInfoResponse(BaseModel):
    """Full registry metadata for one tool (admin surface)."""

    key: str
    sdk_name: str
    description: str
    permission: str
    allowed_roles: List[str] = []
    services: List[str] = []
    tags: List[str] = []
    params_schema: Optional[dict] = None
    module: str


class WorkflowCapabilityResponse(BaseModel):
    kind: str
    title: str
    description: str = ""
    stage_keys: List[str] = []


class CapabilitiesResponse(BaseModel):
    enabled: bool
    agents: List[CapabilityResponse]
    workflows: List[WorkflowCapabilityResponse] = []
