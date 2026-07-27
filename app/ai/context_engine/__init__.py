"""AI Context Engine (Phase 4 of the Educational Agent OS).

Builds the complete, strongly typed, IMMUTABLE execution context before an
agent runs: user, permissions, workflow/stage/artifacts, conversation
history, institution settings, academic policies, course information,
previous outputs, and knowledge references.

Pure data assembly — no LLM logic lives here (and never will; rendering a
context into prompt text is a consumer concern).
"""
from app.ai.context_engine.engine import (  # noqa: F401
    ContextEngine,
    ContextRequest,
    build_context,
    build_for_identity,
    register_provider,
)
from app.ai.context_engine.models import AgentExecutionContext  # noqa: F401
