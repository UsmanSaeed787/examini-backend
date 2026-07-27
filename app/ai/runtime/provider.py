"""The ONLY place an LLM client is constructed (design rule 4/6).

Reproduces — and centralizes — the platform's existing provider convention:
a model name starting with ``gemini`` routes to Google's OpenAI-compatible
endpoint; anything else uses the default OpenAI base URL. Both share the
existing OPENAI_API_KEY. AI_MODEL (if set) overrides OPENAI_MODEL.
"""
from functools import lru_cache

from app.ai.config import ai_settings
from app.ai.runtime.errors import AIRunFailedError
from app.config import settings

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"


def resolve_model_name() -> str:
    return ai_settings.model or settings.openai_model


def is_gemini(model_name: str) -> bool:
    return model_name.lower().startswith("gemini")


@lru_cache
def _client(base_url: str | None):
    from openai import AsyncOpenAI

    if not settings.openai_api_key:
        raise AIRunFailedError("AI is not configured (OPENAI_API_KEY missing)")
    return AsyncOpenAI(api_key=settings.openai_api_key, base_url=base_url)


def build_model(model_name: str | None = None):
    """Return the SDK Model used by a run (injected via RunConfig so agent
    definitions stay model-agnostic). model_name overrides the platform
    default — the per-agent ModelOverrides seam; the OpenAI-vs-Gemini
    base-url routing is re-evaluated per resolved name."""
    from agents import OpenAIChatCompletionsModel, set_tracing_disabled

    if not ai_settings.tracing_enabled:
        set_tracing_disabled(True)
    name = model_name or resolve_model_name()
    return OpenAIChatCompletionsModel(
        model=name,
        openai_client=_client(GEMINI_BASE_URL if is_gemini(name) else None),
    )
