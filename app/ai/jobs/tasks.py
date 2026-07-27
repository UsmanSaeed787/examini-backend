"""Fire-and-forget task scheduling for detached background work.

Two things this does that a bare ``asyncio.create_task`` does not:

1. **Keeps a strong reference.** The event loop only holds a weak reference to
   a task, so a task nobody references can be garbage-collected mid-flight —
   the failure looks like work that silently never happened.
2. **Never lets an exception vanish.** A detached task's exception is
   otherwise only reported when the task object is finalized.

Deliberately in-process: a run is bound to the worker that started it. Polling
from another worker still reads the correct state because progress lives in the
database, and a worker dying mid-run is handled by the callers' staleness
reclamation. Swapping in a real queue later means changing only this module.
"""
import asyncio
import logging
from typing import Any, Coroutine, Set

logger = logging.getLogger(__name__)

_TASKS: Set[asyncio.Task] = set()


def spawn(coro: Coroutine[Any, Any, Any], *, label: str) -> asyncio.Task:
    """Run `coro` detached from the request that created it."""
    task = asyncio.create_task(coro, name=label)
    _TASKS.add(task)

    def _done(finished: asyncio.Task) -> None:
        _TASKS.discard(finished)
        if finished.cancelled():
            return
        error = finished.exception()
        if error is not None:
            # The pipeline records its own failure on the workflow row; this is
            # the last-resort log for anything that escaped that.
            logger.exception("Background task '%s' failed", label, exc_info=error)

    task.add_done_callback(_done)
    return task


def active_count() -> int:
    """Number of detached tasks currently running in this worker."""
    return len(_TASKS)
