"""AI-layer error types and their mapping onto the app's standard envelope.

Every failure that can leave the AI layer becomes an ``AIError`` subclass with
a stable code, rendered by ``setup_ai_error_handlers`` in the same
``{"error": {code, message, details}}`` shape the existing middleware uses.
Raw provider/SDK text is never forwarded to clients.
"""
from fastapi import Request
from fastapi.responses import JSONResponse


class AIError(Exception):
    code = "AI_ERROR"
    status_code = 500

    def __init__(self, message: str = "AI error", details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class AIDisabledError(AIError):
    code = "AI_DISABLED"
    status_code = 403


class AIQuotaExceededError(AIError):
    code = "AI_QUOTA_EXCEEDED"
    status_code = 429


class AIGuardrailRejectedError(AIError):
    code = "AI_GUARDRAIL_REJECTED"
    status_code = 422


class AIRunTimeoutError(AIError):
    code = "AI_RUN_TIMEOUT"
    status_code = 504


class AIRunFailedError(AIError):
    code = "AI_RUN_FAILED"
    status_code = 502


class AIProviderRateLimitedError(AIError):
    """The model provider throttled us — distinct from AI_QUOTA_EXCEEDED, which
    is this platform's own per-user daily budget. Same 429 to the client, but
    the cause and the fix are different: one is the teacher's allowance, the
    other is the deployment's plan."""

    code = "AI_PROVIDER_RATE_LIMITED"
    status_code = 429


def describe_error(exc: Exception) -> str:
    """Human-readable reason for a failure, including the specifics.

    An AIError carries the interesting part in ``details`` — a guardrail
    tripwire puts the individual validation errors there. Without this a
    caller only ever sees "The request or the AI output failed validation",
    which tells the user nothing about what to change.
    """
    message = getattr(exc, "message", None) or str(exc)
    details = getattr(exc, "details", None)
    if isinstance(details, dict):
        errors = details.get("errors")
        if isinstance(errors, (list, tuple)) and errors:
            return f"{message}: " + "; ".join(str(e) for e in errors)
        cause = details.get("cause")
        if cause:
            return f"{message}: {cause}"
    return message


def map_sdk_exception(exc: Exception) -> AIError:
    """Translate SDK / asyncio failures into stable AIError types.

    Imported lazily so the app can start without the openai-agents package
    when the AI layer is disabled.
    """
    if isinstance(exc, AIError):
        return exc
    if isinstance(exc, TimeoutError):
        return AIRunTimeoutError("The AI run exceeded its time limit")

    try:
        from agents.exceptions import (
            AgentsException,
            InputGuardrailTripwireTriggered,
            MaxTurnsExceeded,
            ModelBehaviorError,
            OutputGuardrailTripwireTriggered,
        )
    except ImportError:  # SDK not installed — generic failure
        return AIRunFailedError("AI run failed")

    if isinstance(exc, (InputGuardrailTripwireTriggered, OutputGuardrailTripwireTriggered)):
        info = getattr(getattr(exc, "guardrail_result", None), "output", None)
        details = getattr(info, "output_info", None) or {}
        return AIGuardrailRejectedError("The request or the AI output failed validation", details=details)
    if isinstance(exc, MaxTurnsExceeded):
        return AIRunFailedError("The AI run did not converge within the allowed number of turns")
    if isinstance(exc, ModelBehaviorError):
        return AIRunFailedError("The model produced an unusable response")

    # Provider throttling arrives as an openai exception, not an AgentsException,
    # so without this it fell through to the catch-all and reported the useless
    # "AI run failed" — hiding a 429 the operator can actually act on.
    try:
        from openai import RateLimitError

        if isinstance(exc, RateLimitError):
            return AIProviderRateLimitedError(
                "The AI provider is rate-limiting requests",
                details={"cause": _provider_reason(exc)},
            )
    except ImportError:
        pass

    if isinstance(exc, AgentsException):
        return AIRunFailedError("AI run failed", details={"cause": _brief(exc)})
    # Catch-all: keep the stable code, but never discard what actually happened.
    return AIRunFailedError("AI run failed", details={"cause": _brief(exc)})


def _brief(exc: Exception) -> str:
    """One-line, client-safe summary of an unmapped failure.

    Deliberately short: enough to diagnose, not a stack trace or raw provider
    payload leaking into an API response."""
    text = " ".join(str(exc).split())
    return f"{type(exc).__name__}: {text[:300]}" if text else type(exc).__name__


def _provider_reason(exc: Exception) -> str:
    """The human-readable half of a provider error, without the JSON noise."""
    text = " ".join(str(exc).split())
    if "quota" in text.lower():
        return (
            "the provider reports the account's quota or rate limit is exhausted "
            "— check the plan and billing, or wait for the window to reset"
        )
    return text[:300]


def setup_ai_error_handlers(app) -> None:
    """Register the AI error envelope. Called from app/main.py after the
    existing setup_error_handlers(); purely additive."""

    @app.exception_handler(AIError)
    async def ai_error_handler(request: Request, exc: AIError):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                }
            },
        )
