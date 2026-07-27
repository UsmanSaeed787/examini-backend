"""DB-backed conversation state implementing the SDK Session protocol.

The SDK-facing face of Conversation Memory: reads/writes go through the
Memory Layer's conversation adapter (app/ai/memory), whose canonical storage
is the ai_messages table — one transcript, two views. Used only by agents
whose registry spec sets ``uses_session=True``; one-shot runs (generation)
skip sessions entirely.
"""
import asyncio
from typing import List, Optional

from app.ai.config import ai_settings
from app.ai.persistence import store


class DBSession:
    """Duck-typed implementation of the openai-agents Session protocol."""

    def __init__(self, session_id: str):
        self.session_id = session_id

    async def get_items(self, limit: Optional[int] = None) -> List[dict]:
        from app.ai.memory.service import memory_service

        return await asyncio.to_thread(
            memory_service.conversation_history,
            self.session_id,
            limit or ai_settings.session_history_limit,
        )

    async def add_items(self, items: List[dict]) -> None:
        from app.ai.memory.service import memory_service

        await asyncio.to_thread(memory_service.append_conversation, self.session_id, items)

    async def pop_item(self) -> Optional[dict]:
        return await asyncio.to_thread(store.pop_session_item, self.session_id)

    async def clear_session(self) -> None:
        from app.ai.memory.service import memory_service

        await asyncio.to_thread(memory_service.clear_conversation, self.session_id)
