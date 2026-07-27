"""Results/item-analysis specialist (strictly read-only tools)."""
from agents import Agent

from app.ai.agents.definitions import AgentDefinition
from app.ai.instructions import load_instructions
from app.ai.tools.registry import sdk_tools
from app.utils.constants import UserRole

KEY = "analytics"
REQUIRED_TOOLS = ("exams.list_own", "exams.get_overview", "results.list_for_exam")


def build() -> Agent:
    return Agent(
        name="Examini Analyst",
        instructions=load_instructions(KEY),
        tools=sdk_tools(*REQUIRED_TOOLS),
    )


DEFINITION = AgentDefinition(
    key=KEY,
    name="Analyst",
    description="Analyzes exam results and question composition",
    factory=build,
    version="1.0.0",
    allowed_roles=(UserRole.TEACHER.value, UserRole.ADMIN.value),
    capabilities=("analysis", "reporting"),
    required_tools=REQUIRED_TOOLS,
    supported_workflows=(),
    uses_session=True,
)
