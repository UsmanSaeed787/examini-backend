from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, Optional
from uuid import UUID, uuid4

if TYPE_CHECKING:
    from app.ai.context_engine.models import AgentExecutionContext


@dataclass
class AIRunContext:
    """Travels through every agent run (as the SDK local context).

    The model never sees this object — it is only available to tools,
    guardrails, and the runtime. Authorization decisions are made from
    ``user_id``/``role`` here, never from anything the model says.
    """

    user_id: UUID
    role: str
    full_name: Optional[str] = None
    agent_key: Optional[str] = None
    request_id: str = field(default_factory=lambda: uuid4().hex)
    run_id: Optional[UUID] = None
    # Deterministic per-run data guardrails/tools may need (e.g. question_config).
    extra: Dict[str, Any] = field(default_factory=dict)
    # Immutable execution snapshot assembled by the Context Engine before the
    # run (None when the engine is disabled). Read-only for consumers.
    snapshot: Optional["AgentExecutionContext"] = None
