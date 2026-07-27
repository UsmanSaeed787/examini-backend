from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings


class AISettings(BaseSettings):
    """AI-layer settings. All env vars are prefixed with AI_ and additive —
    nothing existing is renamed. Model/key default to the platform's existing
    OPENAI_MODEL / OPENAI_API_KEY (see runtime/provider.py)."""

    # Feature flags (everything off by default — Phase 0 posture)
    enabled: bool = False
    use_agents_for_generation: bool = False
    # Phase 6: run the assessment workflow's curriculum_analysis stage
    # through the Curriculum Analyst agent instead of the deterministic
    # inventory-only handler.
    use_curriculum_analyst: bool = False
    # Phase 7: run the assessment_design stage through the Assessment
    # Designer agent instead of the deterministic normalization handler.
    use_assessment_designer: bool = False
    # Phase 8: run the quality_review stage through the Quality Reviewer
    # agent in addition to the deterministic structural checks.
    use_quality_reviewer: bool = False
    # Phase 9: difficulty_analysis supports two modes — "deterministic"
    # (statistics only, no model) and "llm" (the same statistics plus agent
    # interpretation).
    difficulty_analysis_mode: str = "deterministic"
    # Phase 10: run the scheduling stage through the Scheduler agent.
    # (The agent advises only — publishing remains a human action.)
    use_scheduler: bool = False
    # Phase 11: materialize an approved AssessmentPlan into a real (draft)
    # exam. Defaults ON — unlike the stage flags above it does not change how
    # an existing stage behaves, it completes the teacher's journey, and it
    # is already gated by the AI_ENABLED master switch (it needs a model
    # run). Set false to keep the pipeline planning-only.
    use_materialization: bool = True

    # Model routing (None -> fall back to app.config.settings.openai_model)
    model: Optional[str] = None

    # Run limits (none of these exist on the legacy OpenAIService path)
    max_turns: int = 8
    run_timeout_seconds: int = 180
    # Ceiling on the model's completion, NOT a reservation — raising it costs
    # nothing on runs that do not need it. It must be generous because
    # reasoning models (gemini-3.x, o-series) spend this same budget thinking
    # before emitting a token of answer, and a payload cut off mid-JSON comes
    # back as a partial object rather than an error.
    max_output_tokens: int = 8192
    # Extra attempts on TRANSIENT provider errors only — rate limits, connection
    # drops, provider 5xx, unusable model output (see
    # runtime/execution.transient_exceptions). Guardrail rejections,
    # cancellations and timeouts are never retried. The machinery existed but
    # shipped disabled, so a single 429 from a burst of stage runs failed a whole
    # workflow that a 2-second wait would have completed.
    max_retries: int = 2
    retry_backoff_seconds: float = 2.0

    # Quotas (enforced per user per UTC day by policies/quotas.py)
    max_runs_per_day: int = 50
    max_tokens_per_day: int = 200_000

    # Generation guardrail knobs
    max_materials_per_run: int = 5
    max_questions_per_exam: int = 100

    # Session memory
    session_history_limit: int = 40

    # Context Engine (Phase 4)
    context_engine_enabled: bool = True
    context_history_limit: int = 20      # conversation messages in the snapshot
    context_previous_runs_limit: int = 5  # prior run summaries in the snapshot

    # Agent registry: comma-separated agent keys hard-disabled via env
    # (AI_DISABLED_AGENTS=grader,analytics). DB flags handle runtime toggling.
    disabled_agents: str = ""

    # SDK tracing export (off: Gemini deployments have no OpenAI trace sink)
    tracing_enabled: bool = False

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        env_prefix = "AI_"
        case_sensitive = False
        extra = "ignore"


@lru_cache
def get_ai_settings() -> AISettings:
    return AISettings()


ai_settings = get_ai_settings()
