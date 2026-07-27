"""Inline execution mode: await the run inside the request."""
from typing import Any, Optional

from app.ai.context import AIRunContext
from app.ai.runtime.runner import execute_run
from app.ai.schemas.runs import RunOutcome


async def submit(
    context: AIRunContext,
    agent_key: str,
    user_input: Any,
    session_id: Optional[str] = None,
    version: Optional[str] = None,
) -> RunOutcome:
    return await execute_run(
        context, agent_key, user_input, session_id=session_id, version=version
    )
