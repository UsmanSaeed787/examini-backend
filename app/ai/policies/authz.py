"""Deny-by-default capability matrix: (role, tool) -> allow.

Enforced in tools/_base.py on EVERY tool invocation — below the model, using
the same UserRole values the REST layer uses. A tool absent from a role's
row cannot be called by that role's runs, regardless of what the model asks.
"""
from app.middleware.error_handler import AuthorizationError
from app.utils.constants import UserRole

TOOL_CAPABILITIES: dict[str, frozenset[str]] = {
    UserRole.ADMIN.value: frozenset(
        {
            "exams.list_own",
            "exams.get_overview",
            "results.list_for_exam",
            "notifications.send",
            "memory.self",
        }
    ),
    UserRole.TEACHER.value: frozenset(
        {
            "materials.list",
            "materials.get_text",
            "exams.list_own",
            "exams.get_overview",
            "results.list_for_exam",
            "results.pending_text_answers",
            "question_bank.save",
            "question_bank.list",
            "notifications.send",
            "workflow.read",
            "memory.self",
        }
    ),
    UserRole.STUDENT.value: frozenset(
        {
            "students.my_enrollments",
            "students.my_upcoming_exams",
            "results.my_results",
            "memory.self",
        }
    ),
}


def is_tool_allowed(role: str, tool_name: str) -> bool:
    return tool_name in TOOL_CAPABILITIES.get(role, frozenset())


def ensure_tool_allowed(role: str, tool_name: str) -> None:
    if not is_tool_allowed(role, tool_name):
        raise AuthorizationError(f"Role '{role}' is not permitted to use tool '{tool_name}'")
