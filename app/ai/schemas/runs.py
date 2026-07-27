"""Internal run-outcome record passed from the runner to callers (facade/API)."""
from dataclasses import dataclass, field
from typing import Any, Optional
from uuid import UUID


@dataclass
class RunOutcome:
    run_id: UUID
    agent_key: str
    status: str
    final_output: Any = None
    usage: dict = field(default_factory=dict)
    session_id: Optional[str] = None
