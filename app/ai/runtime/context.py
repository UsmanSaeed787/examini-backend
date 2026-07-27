"""Runtime execution context: correlation + control-flow state that travels
with one unit of execution.

Separation of concerns with app.ai.context.AIRunContext:
- AIRunContext  = WHO (identity/role) — what tools and authz consume.
- ExecutionContext = WHERE/HOW (correlation ids, attempt, cancellation) —
  what the kernel consumes. It carries the identity, never replaces it.
"""
from dataclasses import dataclass, field, replace
from typing import Optional
from uuid import UUID, uuid4

from app.ai.context import AIRunContext
from app.ai.runtime.lifecycle import CancellationToken


@dataclass
class ExecutionContext:
    identity: AIRunContext
    trace_id: str = field(default_factory=lambda: uuid4().hex)
    run_id: Optional[UUID] = None
    workflow_id: Optional[UUID] = None
    stage_key: Optional[str] = None
    attempt: int = 1
    cancel_token: CancellationToken = field(default_factory=CancellationToken)

    def derive(self, **overrides) -> "ExecutionContext":
        """Child context sharing the trace and cancellation scope."""
        return replace(self, **overrides)
