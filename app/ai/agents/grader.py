"""Text-answer grading specialist (proposes scores; persistence stays a
service-layer extension — the exam_results.reviewed_by seam)."""
from agents import Agent

from app.ai.agents.definitions import AgentDefinition
from app.ai.instructions import load_instructions
from app.ai.tools.registry import sdk_tools
from app.utils.constants import UserRole

KEY = "grader"
REQUIRED_TOOLS = ("exams.get_overview", "results.pending_text_answers", "results.list_for_exam")


def build() -> Agent:
    return Agent(
        name="Examini Grader",
        instructions=load_instructions(KEY),
        tools=sdk_tools(*REQUIRED_TOOLS),
    )


DEFINITION = AgentDefinition(
    key=KEY,
    name="Grader",
    description="Proposes scores for ungraded short/long text answers",
    factory=build,
    version="1.0.0",
    allowed_roles=(UserRole.TEACHER.value,),
    capabilities=("grading", "review"),
    required_tools=REQUIRED_TOOLS,
    supported_workflows=(),
    uses_session=True,
)
