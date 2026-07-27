"""Student study-guidance specialist — own-data, read-only tool scope."""
from agents import Agent

from app.ai.agents.definitions import AgentDefinition
from app.ai.instructions import load_instructions
from app.ai.tools.registry import sdk_tools
from app.utils.constants import UserRole

KEY = "student_assistant"
REQUIRED_TOOLS = (
    "students.my_enrollments",
    "students.my_upcoming_exams",
    "results.my_results",
    "memory.remember",
    "memory.recall",
)


def build() -> Agent:
    return Agent(
        name="Examini Study Assistant",
        instructions=load_instructions(KEY),
        tools=sdk_tools(*REQUIRED_TOOLS),
    )


DEFINITION = AgentDefinition(
    key=KEY,
    name="Study Assistant",
    description="Study guidance over the student's own exams and results",
    factory=build,
    version="1.0.0",
    allowed_roles=(UserRole.STUDENT.value,),
    capabilities=("guidance",),
    required_tools=REQUIRED_TOOLS,
    supported_workflows=(),
    uses_session=True,
)
