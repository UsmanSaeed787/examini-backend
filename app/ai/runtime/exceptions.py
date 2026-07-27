"""Canonical runtime exception surface.

Extends the HTTP-mapped AIError family in errors.py with lifecycle-specific
failures. Everything here subclasses AIError, so the single handler
registered by setup_ai_error_handlers() covers the whole kernel — no new
wiring needed anywhere."""
from app.ai.runtime.errors import (  # noqa: F401  (re-exported as the one import point)
    AIDisabledError,
    AIError,
    AIGuardrailRejectedError,
    AIProviderRateLimitedError,
    AIQuotaExceededError,
    AIRunFailedError,
    AIRunTimeoutError,
    describe_error,
    map_sdk_exception,
)


class ExecutionCancelledError(AIError):
    code = "AI_RUN_CANCELLED"
    status_code = 409


class RetryExhaustedError(AIRunFailedError):
    code = "AI_RETRY_EXHAUSTED"
    status_code = 502


class RegistryError(AIError):
    code = "AI_REGISTRY_ERROR"
    status_code = 500


class AgentDisabledError(AIError):
    code = "AI_AGENT_DISABLED"
    status_code = 403


__all__ = [
    "AIError",
    "AIDisabledError",
    "AIQuotaExceededError",
    "AIProviderRateLimitedError",
    "AIGuardrailRejectedError",
    "AIRunTimeoutError",
    "AIRunFailedError",
    "ExecutionCancelledError",
    "RetryExhaustedError",
    "RegistryError",
    "AgentDisabledError",
    "map_sdk_exception",
    "describe_error",
]
