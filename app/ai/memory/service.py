"""MemoryService — the typed facade the rest of the AI layer uses.

Routes scopes to stores: SHORT_TERM lives in an in-process store (ephemeral
by definition), every other scope in the durable store. Both are injectable
(`set_stores`), which is also what makes the layer provider-independent in
practice — tests and future backends swap stores, callers never change.

Conversation memory is an ADAPTER over the existing ai_messages transcript
(persistence/store.py) — one canonical storage, never double-stored."""
import uuid
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from app.ai.memory.interfaces import (
    MemoryQuery,
    MemoryRecord,
    MemoryScope,
    MemoryStore,
    freeze_content,
)
from app.ai.memory.stores import DatabaseMemoryStore, InProcessMemoryStore, ttl_to_expiry


class MemoryService:
    def __init__(
        self,
        durable: Optional[MemoryStore] = None,
        short_term: Optional[MemoryStore] = None,
    ):
        self._durable: MemoryStore = durable if durable is not None else DatabaseMemoryStore()
        self._short_term: MemoryStore = short_term if short_term is not None else InProcessMemoryStore()

    def set_stores(
        self,
        durable: Optional[MemoryStore] = None,
        short_term: Optional[MemoryStore] = None,
    ) -> tuple:
        """Swap backends (returns the previous pair) — DI for tests/providers."""
        previous = (self._durable, self._short_term)
        if durable is not None:
            self._durable = durable
        if short_term is not None:
            self._short_term = short_term
        return previous

    def _store_for(self, scope: MemoryScope) -> MemoryStore:
        return self._short_term if scope == MemoryScope.SHORT_TERM else self._durable

    # ------------------------------------------------------------ generic API

    def remember(
        self,
        scope: MemoryScope,
        scope_ref: str,
        user_id: UUID,
        content: Dict[str, Any],
        key: Optional[str] = None,
        importance: float = 0.0,
        ttl_seconds: Optional[int] = None,
    ) -> MemoryRecord:
        record = MemoryRecord(
            id=uuid.uuid4(),
            scope=scope,
            scope_ref=scope_ref,
            user_id=user_id,
            content=freeze_content(content),
            key=key,
            importance=importance,
            expires_at=ttl_to_expiry(ttl_seconds),
        )
        return self._store_for(scope).append(record)

    def recall(
        self,
        scope: MemoryScope,
        scope_ref: str,
        user_id: UUID,
        key: Optional[str] = None,
        query: Optional[str] = None,
        limit: int = 20,
    ) -> Tuple[MemoryRecord, ...]:
        return self._store_for(scope).recall(
            MemoryQuery(scope=scope, scope_ref=scope_ref, user_id=user_id, key=key, query=query, limit=limit)
        )

    def forget(
        self, scope: MemoryScope, scope_ref: str, user_id: UUID, key: Optional[str] = None
    ) -> int:
        return self._store_for(scope).forget(scope, scope_ref, user_id, key)

    # ------------------------------------------------------------ typed scopes

    def remember_workflow(self, workflow_id: UUID, user_id: UUID, content: dict, key=None, **kw) -> MemoryRecord:
        return self.remember(MemoryScope.WORKFLOW, str(workflow_id), user_id, content, key=key, **kw)

    def recall_workflow(self, workflow_id: UUID, user_id: UUID, **kw) -> Tuple[MemoryRecord, ...]:
        return self.recall(MemoryScope.WORKFLOW, str(workflow_id), user_id, **kw)

    def remember_session(self, session_id: str, user_id: UUID, content: dict, key=None, **kw) -> MemoryRecord:
        return self.remember(MemoryScope.SESSION, session_id, user_id, content, key=key, **kw)

    def recall_session(self, session_id: str, user_id: UUID, **kw) -> Tuple[MemoryRecord, ...]:
        return self.recall(MemoryScope.SESSION, session_id, user_id, **kw)

    def remember_artifact(
        self, workflow_id: UUID, stage_key: str, user_id: UUID, content: dict, key=None, **kw
    ) -> MemoryRecord:
        return self.remember(MemoryScope.ARTIFACT, f"{workflow_id}:{stage_key}", user_id, content, key=key, **kw)

    def recall_artifact(self, workflow_id: UUID, stage_key: str, user_id: UUID, **kw) -> Tuple[MemoryRecord, ...]:
        return self.recall(MemoryScope.ARTIFACT, f"{workflow_id}:{stage_key}", user_id, **kw)

    def remember_agent(self, user_id: UUID, agent_key: str, content: dict, key=None, **kw) -> MemoryRecord:
        return self.remember(MemoryScope.AGENT, agent_key, user_id, content, key=key, **kw)

    def recall_agent(self, user_id: UUID, agent_key: str, **kw) -> Tuple[MemoryRecord, ...]:
        return self.recall(MemoryScope.AGENT, agent_key, user_id, **kw)

    def remember_short_term(
        self, ref: str, user_id: UUID, content: dict, ttl_seconds: int = 900, key=None
    ) -> MemoryRecord:
        return self.remember(
            MemoryScope.SHORT_TERM, ref, user_id, content, key=key, ttl_seconds=ttl_seconds
        )

    def recall_short_term(self, ref: str, user_id: UUID, **kw) -> Tuple[MemoryRecord, ...]:
        return self.recall(MemoryScope.SHORT_TERM, ref, user_id, **kw)

    # ------------------------------------------------------------ conversation

    def conversation_history(self, session_id: str, limit: Optional[int] = None) -> List[dict]:
        """Adapter: the canonical transcript from ai_messages (also what the
        SDK session uses via runtime/sessions.py)."""
        from app.ai.persistence import store

        return store.get_session_items(session_id, limit)

    def append_conversation(self, session_id: str, items: List[dict]) -> None:
        from app.ai.persistence import store

        store.add_session_items(session_id, items)

    def clear_conversation(self, session_id: str) -> None:
        from app.ai.persistence import store

        store.clear_session(session_id)


memory_service = MemoryService()
