"""Memory interfaces — the provider-independent contract.

Nothing here imports SQLAlchemy, the SDK, or any concrete backend. A store
is anything satisfying MemoryStore; retrieval semantics (`query` = substring
match today, semantic similarity tomorrow) are owned by the implementation
behind the same signature."""
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping, Optional, Protocol, Tuple, runtime_checkable
from uuid import UUID

EMPTY_CONTENT: Mapping[str, Any] = MappingProxyType({})


class MemoryScope(str, Enum):
    WORKFLOW = "workflow"
    SESSION = "session"
    CONVERSATION = "conversation"
    ARTIFACT = "artifact"
    AGENT = "agent"
    SHORT_TERM = "short_term"
    LONG_TERM = "long_term"  # reserved — see SemanticMemoryStore


@dataclass(frozen=True)
class MemoryRecord:
    """One remembered fact. Immutable; content is a read-only mapping."""

    id: UUID
    scope: MemoryScope
    scope_ref: str            # workflow_id / session_id / "wf:stage" / agent_key / free ref
    user_id: UUID
    content: Mapping[str, Any] = EMPTY_CONTENT
    key: Optional[str] = None  # optional stable label; write with same key = upsert
    importance: float = 0.0
    created_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None


@dataclass(frozen=True)
class MemoryQuery:
    scope: MemoryScope
    scope_ref: str
    user_id: UUID
    key: Optional[str] = None
    query: Optional[str] = None   # retrieval hint; impl-defined semantics
    limit: int = 20
    include_expired: bool = False


@runtime_checkable
class MemoryStore(Protocol):
    """Persistence + retrieval contract every backend implements."""

    def append(self, record: MemoryRecord) -> MemoryRecord: ...
    def recall(self, query: MemoryQuery) -> Tuple[MemoryRecord, ...]: ...
    def forget(self, scope: MemoryScope, scope_ref: str, user_id: UUID, key: Optional[str] = None) -> int: ...
    def clear_scope(self, scope: MemoryScope, scope_ref: str) -> int: ...


@runtime_checkable
class SemanticMemoryStore(Protocol):
    """FUTURE long-term memory seam (deliberately unimplemented in v1):
    an embedding-backed store plugs in behind this contract without touching
    MemoryService callers."""

    def index(self, record: MemoryRecord) -> None: ...
    def similar(self, user_id: UUID, text: str, limit: int = 10) -> Tuple[MemoryRecord, ...]: ...


def freeze_content(content: Optional[dict]) -> Mapping[str, Any]:
    return MappingProxyType(dict(content)) if content else EMPTY_CONTENT
