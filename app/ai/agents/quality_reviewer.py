"""Quality Reviewer — third business agent (Phase 8).

Consumes the AssessmentBlueprint (with its curriculum outline and the
institution's academic policies) and returns the review half of the
QualityReport: a verdict per required dimension, attributed observations,
and a summary.

Like the Assessment Designer it is a PURE REVIEW agent:
- no tools -> no database access;
- **no workflow orchestration** — it never decides stage transitions,
  approvals, or whether the pipeline proceeds. It also cannot clear a
  blocker: the authoritative `passed` gate is computed deterministically by
  the stage handler, which only ever ADDS the agent's blockers to it.
"""
from agents import (
    Agent,
    AgentOutputSchema,
    GuardrailFunctionOutput,
    RunContextWrapper,
    output_guardrail,
)

from app.ai.agents.definitions import AgentDefinition
from app.ai.guardrails.output import validate_quality_review
from app.ai.instructions import load_instructions
from app.ai.schemas.outputs import QualityReviewOutput
from app.utils.constants import UserRole

KEY = "quality_reviewer"
REQUIRED_TOOLS: tuple[str, ...] = ()


@output_guardrail
async def _review_guardrail(
    ctx: RunContextWrapper, agent: Agent, output: QualityReviewOutput
) -> GuardrailFunctionOutput:
    errors = validate_quality_review(output)
    return GuardrailFunctionOutput(output_info={"errors": errors}, tripwire_triggered=bool(errors))


def build() -> Agent:
    return Agent(
        name="Examini Quality Reviewer",
        instructions=load_instructions(KEY),
        tools=[],  # intentionally none — see module docstring
        # non-strict schema: works on both OpenAI and the Gemini
        # OpenAI-compatible endpoint (the deployed provider).
        output_type=AgentOutputSchema(QualityReviewOutput, strict_json_schema=False),
        output_guardrails=[_review_guardrail],
    )


DEFINITION = AgentDefinition(
    key=KEY,
    name="Quality Reviewer",
    description="Reviews an assessment blueprint for coverage, balance, distribution, "
    "Bloom alignment, and policy compliance",
    factory=build,
    version="1.0.0",
    allowed_roles=(UserRole.TEACHER.value,),
    capabilities=("review", "quality", "assessment"),
    required_tools=REQUIRED_TOOLS,
    supported_workflows=("assessment",),
    structured_output="QualityReviewOutput",
    uses_session=False,
    api_invocable=False,  # workflow-stage specialist; runs via the stage handler
)
