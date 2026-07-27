"""Unit tests for the Tool Registry (Phase 3): discovery, registration
validation, the execution pipeline (authz -> validation -> DI -> error
mapping), and the SDK bridge. Scratch tools avoid the DB entirely via
dependency injection."""
from uuid import uuid4

import pytest
from pydantic import BaseModel, Field

from app.ai.context import AIRunContext
from app.ai.runtime.exceptions import RegistryError
from app.ai.tools import registry as tools
from app.middleware.error_handler import AuthorizationError, NotFoundError

TEACHER = lambda: AIRunContext(user_id=uuid4(), role="teacher")  # noqa: E731
STUDENT = lambda: AIRunContext(user_id=uuid4(), role="student")  # noqa: E731


class EchoParams(BaseModel):
    value: str = Field(min_length=1)


@pytest.fixture
def scratch_tool():
    definition = tools.ToolDefinition(
        key="scratch.echo",
        description="test-only echo",
        impl=lambda ctx, params: {"echo": params.value, "role": ctx.identity.role},
        permission="exams.list_own",  # teacher-granted capability
        params_model=EchoParams,
    )
    tools.register(definition, override=True)
    yield definition
    tools.unregister("scratch.echo")


class TestDiscoveryAndMetadata:
    def test_discovers_all_tool_modules(self):
        count = tools.discover(force=True)
        assert count >= 14
        for key in (
            "materials.list", "materials.get_text",
            "exams.list_own", "exams.get_overview",
            "results.list_for_exam", "results.pending_text_answers", "results.my_results",
            "students.my_enrollments", "students.my_upcoming_exams",
            "question_bank.save", "question_bank.list",
            "notifications.send",
            "workflow.get_assessment_workflow", "workflow.get_stage_artifact",
        ):
            assert tools.get(key).key == key

    def test_workflow_tools_share_one_permission(self):
        assert tools.get("workflow.get_assessment_workflow").permission == "workflow.read"
        assert tools.get("workflow.get_stage_artifact").permission == "workflow.read"

    def test_metadata_and_role_derivation(self):
        entries = {e["key"]: e for e in tools.list_all()}
        materials_list = entries["materials.list"]
        assert materials_list["allowed_roles"] == ["teacher"]
        assert "MaterialService" in materials_list["services"]
        assert materials_list["params_schema"]["properties"].get("class_id") is not None
        assert entries["results.list_for_exam"]["allowed_roles"] == ["admin", "teacher"]

    def test_unknown_tool_raises(self):
        with pytest.raises(NotFoundError):
            tools.get("no.such_tool")


class TestRegistrationValidation:
    def test_orphan_permission_rejected(self):
        orphan = tools.ToolDefinition(
            key="scratch.orphan",
            description="permission nobody has",
            impl=lambda ctx, params: None,
            permission="not.a_real_capability",
        )
        with pytest.raises(RegistryError):
            tools.register(orphan)

    def test_duplicate_key_rejected_unless_override(self, scratch_tool):
        with pytest.raises(RegistryError):
            tools.register(scratch_tool)
        tools.register(scratch_tool, override=True)


class TestExecutionPipeline:
    async def test_success_path(self, scratch_tool):
        result = await tools.execute_tool(scratch_tool, TEACHER(), '{"value": "hi"}')
        assert result == {"echo": "hi", "role": "teacher"}

    async def test_authorization_raises_hard(self, scratch_tool):
        with pytest.raises(AuthorizationError):
            await tools.execute_tool(scratch_tool, STUDENT(), '{"value": "hi"}')

    async def test_invalid_arguments_are_model_readable(self, scratch_tool):
        result = await tools.execute_tool(scratch_tool, TEACHER(), '{"value": ""}')
        assert result["error"] == "InvalidArguments"
        result = await tools.execute_tool(scratch_tool, TEACHER(), "not json")
        assert result["error"] == "InvalidArguments"

    async def test_domain_errors_are_model_readable(self):
        def failing(ctx, params):
            raise NotFoundError("Exam not found")

        definition = tools.ToolDefinition(
            key="scratch.fail",
            description="raises domain error",
            impl=failing,
            permission="exams.list_own",
        )
        tools.register(definition, override=True)
        try:
            result = await tools.execute_tool(definition, TEACHER(), "")
            assert result == {"error": "NotFoundError", "message": "Exam not found"}
        finally:
            tools.unregister("scratch.fail")

    async def test_value_error_mapped_to_invalid_arguments(self):
        definition = tools.ToolDefinition(
            key="scratch.baduuid",
            description="raises ValueError",
            impl=lambda ctx, params: (_ for _ in ()).throw(ValueError("badly formed UUID")),
            permission="exams.list_own",
        )
        tools.register(definition, override=True)
        try:
            result = await tools.execute_tool(definition, TEACHER(), "")
            assert result["error"] == "InvalidArguments"
        finally:
            tools.unregister("scratch.baduuid")

    async def test_dependency_injection(self, scratch_tool):
        marker = {"used": False}

        class FakeScope:
            def __enter__(self):
                marker["used"] = True
                return None

            def __exit__(self, *exc):
                return False

        def uses_db(ctx, params):
            with ctx.db():
                return {"ok": True}

        definition = tools.ToolDefinition(
            key="scratch.db",
            description="touches injected db",
            impl=uses_db,
            permission="exams.list_own",
        )
        tools.register(definition, override=True)
        previous = tools.set_dependencies(tools.ToolDependencies(session_scope=FakeScope))
        try:
            result = await tools.execute_tool(definition, TEACHER(), "")
            assert result == {"ok": True}
            assert marker["used"] is True
        finally:
            tools.set_dependencies(previous)
            tools.unregister("scratch.db")


class TestSdkBridge:
    def test_sdk_tools_built_with_sanitized_names(self):
        from agents import FunctionTool

        built = tools.sdk_tools("materials.list", "workflow.get_stage_artifact")
        assert all(isinstance(t, FunctionTool) for t in built)
        assert built[0].name == "materials_list"
        assert built[1].name == "workflow_get_stage_artifact"

    def test_sdk_tools_cached(self):
        first = tools.sdk_tools("materials.list")[0]
        second = tools.sdk_tools("materials.list")[0]
        assert first is second
