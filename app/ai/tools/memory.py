"""Agent-memory tools — how assistants persist and retrieve facts across
conversations. Strictly self-scoped: records are keyed to the calling user
AND the executing agent; no tool can read another user's or agent's memory."""
from typing import Optional

from pydantic import BaseModel, Field

from app.ai.memory.service import memory_service
from app.ai.tools.registry import ToolContext, tool


class RememberParams(BaseModel):
    text: str = Field(min_length=1, max_length=2000, description="The fact to remember")
    key: Optional[str] = Field(
        default=None, max_length=100,
        description="Optional stable label; remembering with the same key overwrites",
    )


class RecallParams(BaseModel):
    query: Optional[str] = Field(default=None, max_length=200, description="Text to search for")
    key: Optional[str] = Field(default=None, max_length=100, description="Exact label to fetch")
    limit: int = Field(default=10, ge=1, le=50)


def _agent_ref(ctx: ToolContext) -> str:
    return ctx.identity.agent_key or "unknown"


@tool(
    key="memory.remember",
    description="Remember a fact about the current user for future conversations "
    "(persists across sessions; same key overwrites).",
    permission="memory.self",
    params=RememberParams,
    services=("MemoryService",),
    tags=("memory", "write", "self"),
)
def remember(ctx: ToolContext, params: RememberParams) -> dict:
    record = memory_service.remember_agent(
        user_id=ctx.identity.user_id,
        agent_key=_agent_ref(ctx),
        content={"text": params.text},
        key=params.key,
    )
    return {"remembered": True, "id": str(record.id), "key": record.key}


@tool(
    key="memory.recall",
    description="Recall previously remembered facts about the current user "
    "(optionally filtered by search text or exact key).",
    permission="memory.self",
    params=RecallParams,
    services=("MemoryService",),
    tags=("memory", "read", "self"),
)
def recall(ctx: ToolContext, params: RecallParams) -> list[dict]:
    records = memory_service.recall_agent(
        user_id=ctx.identity.user_id,
        agent_key=_agent_ref(ctx),
        key=params.key,
        query=params.query,
        limit=params.limit,
    )
    return [
        {
            "key": r.key,
            "text": r.content.get("text"),
            "remembered_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in records
    ]
