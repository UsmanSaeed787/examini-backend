"""Exam generation specialist.

Structured output (GeneratedExamOutput) + SDK guardrails wrapping the pure
validators in guardrails/. The question_config travels in the run context
(AIRunContext.extra) so guardrails validate deterministically — the model
never gets to define what "valid" means."""
from agents import (
    Agent,
    AgentOutputSchema,
    GuardrailFunctionOutput,
    RunContextWrapper,
    input_guardrail,
    output_guardrail,
)

from app.ai.agents.definitions import AgentDefinition, ModelOverrides
from app.ai.guardrails.input import validate_question_config
from app.ai.guardrails.output import validate_generated_exam
from app.ai.instructions import load_instructions
from app.ai.schemas.outputs import GeneratedExamOutput
from app.ai.tools.registry import sdk_tools
from app.utils.constants import UserRole

KEY = "exam_generator"
REQUIRED_TOOLS = ("materials.list", "materials.get_text")


@input_guardrail
async def _config_guardrail(ctx: RunContextWrapper, agent: Agent, input) -> GuardrailFunctionOutput:
    errors = validate_question_config(ctx.context.extra.get("question_config") or {})
    return GuardrailFunctionOutput(output_info={"errors": errors}, tripwire_triggered=bool(errors))


@output_guardrail
async def _exam_guardrail(
    ctx: RunContextWrapper, agent: Agent, output: GeneratedExamOutput
) -> GuardrailFunctionOutput:
    errors = validate_generated_exam(output, ctx.context.extra.get("question_config") or {})
    return GuardrailFunctionOutput(output_info={"errors": errors}, tripwire_triggered=bool(errors))


def build() -> Agent:
    return Agent(
        name="Examini Exam Generator",
        instructions=load_instructions(KEY),
        tools=sdk_tools(*REQUIRED_TOOLS),
        # non-strict schema: works on both OpenAI and the Gemini
        # OpenAI-compatible endpoint (the deployed provider).
        output_type=AgentOutputSchema(GeneratedExamOutput, strict_json_schema=False),
        input_guardrails=[_config_guardrail],
        output_guardrails=[_exam_guardrail],
    )


DEFINITION = AgentDefinition(
    key=KEY,
    name="Exam Generator",
    description="Generates exam questions from uploaded course materials",
    factory=build,
    version="1.0.0",
    # The only agent whose output volume is set by the teacher: every other
    # agent returns bounded prose, this one returns N questions with options.
    # At the previous 4096 ceiling a 10-question request was truncated mid-JSON
    # and surfaced as "expected 10 questions, got 1".
    model_overrides=ModelOverrides(max_output_tokens=16384),
    allowed_roles=(UserRole.TEACHER.value,),
    capabilities=("generation", "assessment"),
    required_tools=REQUIRED_TOOLS,
    supported_workflows=("assessment",),
    structured_output="GeneratedExamOutput",
    uses_session=False,
    api_invocable=False,  # facade-only: deterministic pre/post steps required
)
