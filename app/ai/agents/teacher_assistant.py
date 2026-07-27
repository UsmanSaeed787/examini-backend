"""Teacher authoring/material-QA specialist."""
from agents import Agent

from app.ai.agents.definitions import AgentDefinition
from app.ai.instructions import load_instructions
from app.ai.tools.registry import sdk_tools
from app.utils.constants import UserRole

KEY = "teacher_assistant"
REQUIRED_TOOLS = (
    "materials.list",
    "materials.get_text",
    "exams.list_own",
    "exams.get_overview",
    "question_bank.save",
    "question_bank.list",
    "notifications.send",
    "workflow.get_assessment_workflow",
    "workflow.get_stage_artifact",
    "memory.remember",
    "memory.recall",
)


def build() -> Agent:
    return Agent(
        name="Examini Teaching Assistant",
        instructions=load_instructions(KEY),
        tools=sdk_tools(*REQUIRED_TOOLS),
    )


DEFINITION = AgentDefinition(
    key=KEY,
    name="Teaching Assistant",
    description="Assists with exam authoring, materials, and the question bank",
    factory=build,
    version="1.0.0",
    allowed_roles=(UserRole.TEACHER.value,),
    capabilities=("authoring", "materials", "question-bank"),
    required_tools=REQUIRED_TOOLS,
    supported_workflows=("assessment",),
    uses_session=True,
)
