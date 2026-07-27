"""Background execution mode: create the run row up-front (so the client
can poll it) and execute detached from the request. A queue/worker adapter
can replace the create_task body later behind the same submit() signature."""
import asyncio
from typing import Any, Optional
from uuid import UUID

from app.ai.context import AIRunContext
from app.ai.persistence import store
from app.ai.runtime.errors import AIError
from app.ai.runtime.runner import execute_run


async def submit(
    context: AIRunContext,
    agent_key: str,
    user_input: Any,
    session_id: Optional[str] = None,
    version: Optional[str] = None,
) -> UUID:
    run_id = await asyncio.to_thread(
        store.create_run,
        context.user_id,
        agent_key,
        user_input if isinstance(user_input, str) else None,
        session_id,
        "queued",
    )

    async def _execute() -> None:
        try:
            await execute_run(
                context,
                agent_key,
                user_input,
                session_id=session_id,
                run_id=run_id,
                version=version,
            )
        except AIError:
            pass  # already recorded on the run row by the runner

    asyncio.create_task(_execute())
    return run_id
