"""Front-door agent for teacher/admin roles — routes via SDK handoffs."""
from agents import Agent

from app.ai.agents import analytics, grader, teacher_assistant
from app.ai.agents.definitions import AgentDefinition
from app.ai.instructions import load_instructions
from app.utils.constants import UserRole

KEY = "triage"


def build() -> Agent:
    return Agent(
        name="Examini Triage",
        instructions=load_instructions(KEY),
        handoffs=[grader.build(), analytics.build(), teacher_assistant.build()],
    )


DEFINITION = AgentDefinition(
    key=KEY,
    name="Triage",
    description="Routes a request to the right specialist",
    factory=build,
    version="1.0.0",
    allowed_roles=(UserRole.TEACHER.value, UserRole.ADMIN.value),
    capabilities=("routing",),
    required_tools=(),  # delegates via handoffs; specialists carry the tools
    supported_workflows=(),
    uses_session=True,
)
