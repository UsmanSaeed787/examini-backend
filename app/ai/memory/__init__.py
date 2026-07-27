"""AI Memory Layer (Phase 5 of the Educational Agent OS).

One provider-independent memory abstraction with typed scopes:

- WORKFLOW      — facts attached to a workflow instance (e.g. rejection feedback)
- SESSION       — notes attached to a conversation session
- CONVERSATION  — the message transcript (canonical storage stays ai_messages;
                  exposed here through an adapter — never double-stored)
- ARTIFACT      — annotations about a produced workflow artifact
- AGENT         — per-user, per-agent persistent facts (the memory tools)
- SHORT_TERM    — TTL scratch (in-process store by default)
- LONG_TERM     — reserved future scope (SemanticMemoryStore seam)

Interfaces know nothing about SQLAlchemy or any provider; the database store
is one implementation, the in-process store another, and a vector/Redis
store later is just another `MemoryStore` passed to `MemoryService`.
"""
from app.ai.memory.interfaces import (  # noqa: F401
    MemoryQuery,
    MemoryRecord,
    MemoryScope,
    MemoryStore,
)
from app.ai.memory.service import MemoryService, memory_service  # noqa: F401
