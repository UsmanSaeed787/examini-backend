"""Curriculum Analyst — the first business agent (Phase 6).

Analyzes uploaded syllabus/teaching materials and produces the analytical
half of the CurriculumOutline artifact: topics, learning outcomes, Bloom's
taxonomy levels, and a summary. Material text is prefetched into the run
input by the stage handler (deterministic, mirrors the generation facade);
the registry tools let the agent re-read a material if it needs more than
the provided excerpt. Structured output only; no database access — the Tool
Registry is its only reach into the platform."""
from agents import (
    Agent,
    AgentOutputSchema,
    GuardrailFunctionOutput,
    RunContextWrapper,
    output_guardrail,
)

from app.ai.agents.definitions import AgentDefinition
from app.ai.guardrails.output import validate_curriculum_analysis
from app.ai.instructions import load_instructions
from app.ai.schemas.outputs import CurriculumAnalysisOutput
from app.ai.tools.registry import sdk_tools
from app.utils.constants import UserRole

KEY = "curriculum_analyst"
REQUIRED_TOOLS = ("materials.list", "materials.get_text")


@output_guardrail
async def _analysis_guardrail(
    ctx: RunContextWrapper, agent: Agent, output: CurriculumAnalysisOutput
) -> GuardrailFunctionOutput:
    allowed_ids = ctx.context.extra.get("material_ids") or ()
    errors = validate_curriculum_analysis(output, allowed_ids)
    return GuardrailFunctionOutput(output_info={"errors": errors}, tripwire_triggered=bool(errors))


def build() -> Agent:
    return Agent(
        name="Examini Curriculum Analyst",
        instructions=load_instructions(KEY),
        tools=sdk_tools(*REQUIRED_TOOLS),
        # non-strict schema: works on both OpenAI and the Gemini
        # OpenAI-compatible endpoint (the deployed provider).
        output_type=AgentOutputSchema(CurriculumAnalysisOutput, strict_json_schema=False),
        output_guardrails=[_analysis_guardrail],
    )


DEFINITION = AgentDefinition(
    key=KEY,
    name="Curriculum Analyst",
    description="Extracts topics, learning outcomes, and Bloom's levels from teaching materials",
    factory=build,
    version="1.0.0",
    allowed_roles=(UserRole.TEACHER.value,),
    capabilities=("analysis", "curriculum", "assessment"),
    required_tools=REQUIRED_TOOLS,
    supported_workflows=("assessment",),
    structured_output="CurriculumAnalysisOutput",
    uses_session=False,
    api_invocable=False,  # workflow-stage specialist; runs via the stage handler
)