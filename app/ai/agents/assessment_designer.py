"""Assessment Designer — second business agent (Phase 7).

Consumes the CurriculumOutline (topics, learning outcomes, Bloom levels,
emphasis) and produces the design half of the AssessmentBlueprint: how the
requested questions distribute across the curriculum.

Deliberately a PURE TRANSFORMATION agent:
- no tools at all -> no database access, direct or indirect;
- no workflow logic (stage transitions/approvals belong to the orchestrator);
- no scheduling (duration/dates are the Scheduler stage's artifact).
Everything it reasons over is placed in the run input by the stage handler.
"""
from agents import (
    Agent,
    AgentOutputSchema,
    GuardrailFunctionOutput,
    RunContextWrapper,
    output_guardrail,
)

from app.ai.agents.definitions import AgentDefinition
from app.ai.guardrails.output import validate_assessment_design
from app.ai.instructions import load_instructions
from app.ai.schemas.outputs import AssessmentDesignOutput
from app.utils.constants import UserRole

KEY = "assessment_designer"
REQUIRED_TOOLS: tuple[str, ...] = ()


@output_guardrail
async def _design_guardrail(
    ctx: RunContextWrapper, agent: Agent, output: AssessmentDesignOutput
) -> GuardrailFunctionOutput:
    extra = ctx.context.extra or {}
    errors = validate_assessment_design(
        output,
        extra.get("topics") or (),
        extra.get("total_questions") or 0,
    )
    return GuardrailFunctionOutput(output_info={"errors": errors}, tripwire_triggered=bool(errors))


def build() -> Agent:
    return Agent(
        name="Examini Assessment Designer",
        instructions=load_instructions(KEY),
        tools=[],  # intentionally none — see module docstring
        # non-strict schema: works on both OpenAI and the Gemini
        # OpenAI-compatible endpoint (the deployed provider).
        output_type=AgentOutputSchema(AssessmentDesignOutput, strict_json_schema=False),
        output_guardrails=[_design_guardrail],
    )


DEFINITION = AgentDefinition(
    key=KEY,
    name="Assessment Designer",
    description="Distributes an exam's questions across curriculum topics and Bloom levels",
    factory=build,
    version="1.0.0",
    allowed_roles=(UserRole.TEACHER.value,),
    capabilities=("design", "assessment"),
    required_tools=REQUIRED_TOOLS,
    supported_workflows=("assessment",),
    structured_output="AssessmentDesignOutput",
    uses_session=False,
    api_invocable=False,  # workflow-stage specialist; runs via the stage handler
)
