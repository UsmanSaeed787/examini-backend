"""Scheduler — fifth business agent (Phase 10), completing the assessment
pipeline's specialist set.

Analyzes the teacher's constraints, the duration the blueprint implies, and
the class's exam calendar, and returns a readiness verdict with reasoning
and recommendations.

**No publishing**: the agent has no tools, so it cannot reach
ExamService.publish_exam or any other mutation — and its output carries no
publish/approval field. Publishing stays a deliberate human action in the
existing teacher API, entirely outside this workflow.
"""
from agents import (
    Agent,
    AgentOutputSchema,
    GuardrailFunctionOutput,
    RunContextWrapper,
    output_guardrail,
)

from app.ai.agents.definitions import AgentDefinition
from app.ai.guardrails.output import validate_schedule_plan
from app.ai.instructions import load_instructions
from app.ai.schemas.outputs import SchedulePlanOutput
from app.utils.constants import UserRole

KEY = "scheduler"
REQUIRED_TOOLS: tuple[str, ...] = ()


@output_guardrail
async def _schedule_guardrail(
    ctx: RunContextWrapper, agent: Agent, output: SchedulePlanOutput
) -> GuardrailFunctionOutput:
    has_window = bool((ctx.context.extra or {}).get("has_window"))
    errors = validate_schedule_plan(output, has_window)
    return GuardrailFunctionOutput(output_info={"errors": errors}, tripwire_triggered=bool(errors))


def build() -> Agent:
    return Agent(
        name="Examini Scheduler",
        instructions=load_instructions(KEY),
        tools=[],  # intentionally none — see module docstring
        # non-strict schema: works on both OpenAI and the Gemini
        # OpenAI-compatible endpoint (the deployed provider).
        output_type=AgentOutputSchema(SchedulePlanOutput, strict_json_schema=False),
        output_guardrails=[_schedule_guardrail],
    )


DEFINITION = AgentDefinition(
    key=KEY,
    name="Scheduler",
    description="Assesses exam timing against teacher constraints, duration needs, and the class calendar",
    factory=build,
    version="1.0.0",
    allowed_roles=(UserRole.TEACHER.value,),
    capabilities=("scheduling", "assessment"),
    required_tools=REQUIRED_TOOLS,
    supported_workflows=("assessment",),
    structured_output="SchedulePlanOutput",
    uses_session=False,
    api_invocable=False,  # workflow-stage specialist; runs via the stage handler
)
