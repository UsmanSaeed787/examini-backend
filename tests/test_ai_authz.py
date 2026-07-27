"""Unit tests for the AI layer's capability matrix and registry access rules."""
import pytest

from app.ai.agents.registry import ensure_agent_allowed, get_spec, list_for_role
from app.ai.policies.authz import ensure_tool_allowed, is_tool_allowed
from app.middleware.error_handler import AuthorizationError, NotFoundError


class TestToolCapabilities:
    def test_teacher_allowed_tools(self):
        assert is_tool_allowed("teacher", "materials.get_text")
        assert is_tool_allowed("teacher", "question_bank.save")

    def test_student_denied_teacher_tools(self):
        assert not is_tool_allowed("student", "materials.get_text")
        assert not is_tool_allowed("student", "results.pending_text_answers")
        assert not is_tool_allowed("student", "notifications.send")

    def test_student_allowed_own_scope(self):
        assert is_tool_allowed("student", "results.my_results")
        assert is_tool_allowed("student", "students.my_enrollments")

    def test_unknown_role_denied_everything(self):
        assert not is_tool_allowed("hacker", "materials.list")

    def test_deny_raises_authorization_error(self):
        with pytest.raises(AuthorizationError):
            ensure_tool_allowed("student", "exams.list_own")

    def test_allow_does_not_raise(self):
        ensure_tool_allowed("teacher", "exams.list_own")


class TestAgentRegistry:
    def test_unknown_agent_raises_not_found(self):
        with pytest.raises(NotFoundError):
            get_spec("nonexistent")

    def test_role_gating(self):
        with pytest.raises(AuthorizationError):
            ensure_agent_allowed("exam_generator", "student")
        assert ensure_agent_allowed("exam_generator", "teacher").key == "exam_generator"

    def test_student_capabilities_listing(self):
        keys = {spec.key for spec in list_for_role("student")}
        assert keys == {"student_assistant"}

    def test_generator_not_api_invocable(self):
        keys = {spec.key for spec in list_for_role("teacher")}
        assert "exam_generator" not in keys  # facade-only
        assert "teacher_assistant" in keys

    def test_all_agents_build(self):
        """Every registered factory constructs a real SDK Agent with its
        instructions asset present."""
        for role in ("teacher", "admin", "student"):
            for spec in list_for_role(role, api_only=False):
                agent = spec.factory()
                assert agent.name
                assert agent.instructions
