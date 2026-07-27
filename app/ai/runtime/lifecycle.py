"""Execution lifecycle: cancellation, timeout, and retry — composed around
any attempt factory (agent runs, stage executions, future tool calls).

This module is deliberately SDK-free and I/O-free: pure asyncio control flow,
fully unit-testable."""
import asyncio
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple, Type
from uuid import UUID

from app.ai.runtime.exceptions import (
    AIRunTimeoutError,
    ExecutionCancelledError,
    RetryExhaustedError,
    describe_error,
    map_sdk_exception,
)
from app.ai.runtime.interfaces import AttemptFactory


class CancellationToken:
    """Cooperative cancellation signal, awaitable by the lifecycle loop."""

    def __init__(self) -> None:
        self._event = asyncio.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    async def wait(self) -> None:
        await self._event.wait()


class CancellationRegistry:
    """run_id -> token, so an API call can cancel an in-flight run in this
    process (inline or background)."""

    def __init__(self) -> None:
        self._tokens: Dict[UUID, CancellationToken] = {}

    def register(self, run_id: UUID, token: CancellationToken) -> None:
        self._tokens[run_id] = token

    def unregister(self, run_id: UUID) -> None:
        self._tokens.pop(run_id, None)

    def cancel(self, run_id: UUID) -> bool:
        token = self._tokens.get(run_id)
        if token is None:
            return False
        token.cancel()
        return True

    def active(self) -> list[UUID]:
        return list(self._tokens.keys())


run_registry = CancellationRegistry()


@dataclass
class RetryPolicy:
    """max_attempts is TOTAL attempts (1 = no retry). Only exceptions matching
    retry_on trigger another attempt; everything else propagates immediately."""

    max_attempts: int = 1
    backoff_seconds: float = 0.0
    retry_on: Tuple[Type[BaseException], ...] = field(default_factory=tuple)


async def run_with_lifecycle(
    factory: AttemptFactory,
    *,
    timeout_seconds: Optional[float] = None,
    retry: Optional[RetryPolicy] = None,
    token: Optional[CancellationToken] = None,
) -> Any:
    """Execute factory() under timeout/retry/cancellation.

    Raises ExecutionCancelledError / AIRunTimeoutError / RetryExhaustedError,
    or the attempt's own exception when it is not retryable."""
    policy = retry or RetryPolicy()
    attempt = 0
    last_error: Optional[BaseException] = None

    while attempt < max(policy.max_attempts, 1):
        attempt += 1
        if token and token.cancelled:
            raise ExecutionCancelledError("The run was cancelled")

        work = asyncio.ensure_future(factory())
        waiters = [work]
        cancel_waiter = None
        if token is not None:
            cancel_waiter = asyncio.ensure_future(token.wait())
            waiters.append(cancel_waiter)

        done, _ = await asyncio.wait(
            waiters, timeout=timeout_seconds, return_when=asyncio.FIRST_COMPLETED
        )

        if work not in done:  # timed out, or cancellation fired first
            work.cancel()
            await asyncio.gather(work, return_exceptions=True)
            if cancel_waiter is not None:
                cancel_waiter.cancel()
                await asyncio.gather(cancel_waiter, return_exceptions=True)
            if token and token.cancelled:
                raise ExecutionCancelledError("The run was cancelled")
            raise AIRunTimeoutError("The AI run exceeded its time limit")

        if cancel_waiter is not None:
            cancel_waiter.cancel()
            await asyncio.gather(cancel_waiter, return_exceptions=True)

        error = work.exception()
        if error is None:
            return work.result()

        last_error = error
        retryable = policy.retry_on and isinstance(error, policy.retry_on)
        if not retryable or attempt >= policy.max_attempts:
            if attempt > 1:
                raise _exhausted(last_error, attempt) from last_error
            raise error
        if policy.backoff_seconds:
            await asyncio.sleep(policy.backoff_seconds * attempt)

    raise RetryExhaustedError("Failed without executing any attempt")  # pragma: no cover


def _exhausted(last_error: BaseException, attempts: int) -> RetryExhaustedError:
    """Retry exhaustion that still says WHY.

    Chaining alone is not enough — the exception is rendered to the client
    through describe_error, so a retried rate limit would report only "Failed
    after 3 attempts" and lose the actionable cause. Worse, the generic 502
    would mask a 429 the caller should treat differently.

    So: keep the RetryExhaustedError type (callers and tests depend on it), but
    when the underlying failure maps to a specifically identified AIError, adopt
    that error's code and status per-instance so the client still reacts
    correctly.
    """
    from app.ai.runtime.exceptions import AIRunFailedError

    mapped = map_sdk_exception(last_error) if isinstance(last_error, Exception) else None
    exhausted = RetryExhaustedError(
        f"Failed after {attempts} attempts",
        details={"cause": describe_error(mapped)} if mapped else None,
    )
    # type(...) is AIRunFailedError == the catch-all, i.e. nothing specific was
    # identified; only override when the cause was actually recognised.
    if mapped is not None and type(mapped) is not AIRunFailedError:
        exhausted.code = mapped.code
        exhausted.status_code = mapped.status_code
    return exhausted
