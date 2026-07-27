"""Difficulty Analyzer — fourth business agent (Phase 9).

Interprets the difficulty statistics the stage handler already computed
(this exam's distribution and index, the teacher's historical figures, the
divergence, and per-exam outcomes) and returns a calibration verdict with
an assessment and recommendations.

This agent powers the stage's **LLM mode**; the deterministic mode produces
the same statistical profile with no model involvement at all. Like the
designer and reviewer it is a pure interpretation agent: no tools (so no
database access), and its output carries no distribution fields, so it
cannot rewrite the difficulty mix it is commenting on.
"""
from agents import (
    Agent,
    AgentOutputSchema,
    GuardrailFunctionOutput,
    RunContextWrapper,
    output_guardrail,
)

from app.ai.agents.definitions import AgentDefinition
from app.ai.guardrails.output import validate_difficulty_analysis
from app.ai.instructions import load_instructions
from app.ai.schemas.outputs import DifficultyAnalysisOutput
from app.utils.constants import UserRole

KEY = "difficulty_analyzer"
REQUIRED_TOOLS: tuple[str, ...] = ()


@output_guardrail
async def _analysis_guardrail(
    ctx: RunContextWrapper, agent: Agent, output: DifficultyAnalysisOutput
) -> GuardrailFunctionOutput:
    has_history = bool((ctx.context.extra or {}).get("has_history"))
    errors = validate_difficulty_analysis(output, has_history)
    return GuardrailFunctionOutput(output_info={"errors": errors}, tripwire_triggered=bool(errors))


def build() -> Agent:
    return Agent(
        name="Examini Difficulty Analyzer",
        instructions=load_instructions(KEY),
        tools=[],  # intentionally none — see module docstring
        # non-strict schema: works on both OpenAI and the Gemini
        # OpenAI-compatible endpoint (the deployed provider).
        output_type=AgentOutputSchema(DifficultyAnalysisOutput, strict_json_schema=False),
        output_guardrails=[_analysis_guardrail],
    )


DEFINITION = AgentDefinition(
    key=KEY,
    name="Difficulty Analyzer",
    description="Interprets an exam's difficulty profile against the teacher's exam history",
    factory=build,
    version="1.0.0",
    allowed_roles=(UserRole.TEACHER.value,),
    capabilities=("analysis", "difficulty", "assessment"),
    required_tools=REQUIRED_TOOLS,
    supported_workflows=("assessment",),
    structured_output="DifficultyAnalysisOutput",
    uses_session=False,
    api_invocable=False,  # workflow-stage specialist; runs via the stage handler
)
