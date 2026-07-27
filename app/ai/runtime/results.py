"""Structured result types every runtime execution returns.

Generic over the output type; no workflow- or agent-specific fields. The
API/facade layers translate these into their own DTOs."""
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Generic, Optional, TypeVar

T = TypeVar("T")


class ExecutionStatus(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


@dataclass
class ExecutionError:
    code: str
    message: str


@dataclass
class ExecutionResult(Generic[T]):
    """Outcome of one unit of execution (an agent run, a stage, a tool)."""

    status: ExecutionStatus
    output: Optional[T] = None
    error: Optional[ExecutionError] = None
    usage: dict = field(default_factory=dict)
    model: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    duration_ms: Optional[float] = None
    attempts: int = 1
    metadata: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == ExecutionStatus.COMPLETED


class PipelineStatus(str, Enum):
    COMPLETED = "completed"  # every stage ran (and auto-approved)
    PAUSED = "paused"        # stopped at a human approval checkpoint
    FAILED = "failed"        # a stage failed; hooks recorded the failure
    IDLE = "idle"            # nothing runnable (already paused/terminal)


@dataclass
class PipelineResult:
    status: PipelineStatus
    stage_key: Optional[str] = None   # stage the pipeline stopped at (if any)
    error: Optional[ExecutionError] = None
    stages_run: int = 0
