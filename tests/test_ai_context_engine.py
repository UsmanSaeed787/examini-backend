"""Unit tests for the Context Engine (Phase 4): immutability, engine
orchestration/DI, failure-safety, pure providers, knowledge composition, and
the identity bridge. DB-backed providers are exercised via fakes."""
import dataclasses
from uuid import UUID, uuid4

import pytest

from app.ai.context import AIRunContext
from app.ai.context_engine import ContextEngine, ContextRequest, build_for_identity
from app.ai.context_engine.engine import _uuid_or_none
from app.ai.context_engine.models import (
    AgentExecutionContext,
    ArtifactRef,
    CourseContext,
    MaterialRef,
    RunSummary,
    UserContext,
    WorkflowContext,
    WorkflowFacet,
    freeze_mapping,
)
from app.ai.context_engine.providers import AcademicPolicyProvider, PermissionsProvider


class FakeProvider:
    def __init__(self, facet, value=None, error=None):
        self.facet = facet
        self._value = value
        self._error = error

    def collect(self, request):
        if self._error:
            raise self._error
        return self._value


def _request(**overrides) -> ContextRequest:
    defaults = dict(user_id=uuid4(), role="teacher", agent_key="grader")
    defaults.update(overrides)
    return ContextRequest(**defaults)


class TestImmutability:
    def test_context_objects_are_frozen(self):
        user = UserContext(user_id=uuid4(), email="t@x.com", role="teacher")
        with pytest.raises(dataclasses.FrozenInstanceError):
            user.role = "admin"
        ctx = AgentExecutionContext(request_id="r", built_at=None, agent_key=None)
        with pytest.raises(dataclasses.FrozenInstanceError):
            ctx.agent_key = "other"

    def test_mappings_are_read_only(self):
        frozen = freeze_mapping({"a": 1})
        assert frozen["a"] == 1
        with pytest.raises(TypeError):
            frozen["a"] = 2  # type: ignore[index]

    def test_collections_are_tuples(self):
        ctx = AgentExecutionContext(request_id="r", built_at=None, agent_key=None)
        assert isinstance(ctx.artifacts, tuple)
        assert isinstance(ctx.knowledge, tuple)
        assert isinstance(ctx.warnings, tuple)


class TestEngine:
    async def test_facets_assemble_into_context(self):
        workflow_id = uuid4()
        engine = ContextEngine(
            providers=[
                FakeProvider("user", UserContext(user_id=uuid4(), email="t@x.com", role="teacher")),
                FakeProvider(
                    "workflow",
                    WorkflowFacet(
                        workflow=WorkflowContext(
                            workflow_id=workflow_id,
                            kind="assessment",
                            title="W",
                            state="in_progress",
                            approval_mode="every_stage",
                        ),
                        artifacts=(
                            ArtifactRef(stage_key="assessment_design", status="approved", revision=1),
                        ),
                    ),
                ),
            ]
        )
        ctx = await engine.build(_request())
        assert ctx.user.email == "t@x.com"
        assert ctx.workflow.workflow_id == workflow_id
        assert ctx.artifacts[0].stage_key == "assessment_design"
        assert ctx.warnings == ()
        assert ctx.request_id  # generated when not supplied

    async def test_provider_failure_becomes_warning_not_crash(self):
        engine = ContextEngine(
            providers=[
                FakeProvider("user", error=RuntimeError("db down")),
                FakeProvider("institution", value=None),
            ]
        )
        ctx = await engine.build(_request())
        assert ctx.user is None
        assert ctx.warnings == ("user: RuntimeError",)

    async def test_register_provider_replaces_same_facet(self):
        engine = ContextEngine(providers=[FakeProvider("user", "OLD")])
        engine.register_provider(
            FakeProvider("user", UserContext(user_id=uuid4(), email="new@x.com", role="admin"))
        )
        ctx = await engine.build(_request())
        assert ctx.user.email == "new@x.com"

    async def test_knowledge_composed_across_facets(self):
        course = CourseContext(
            class_id=uuid4(),
            name="Grade 10",
            materials=(
                MaterialRef(material_id=uuid4(), title="Notes", file_type="pdf", parseable=True),
                MaterialRef(material_id=uuid4(), title="Slides", file_type="pptx"),
            ),
        )
        workflow = WorkflowFacet(
            workflow=WorkflowContext(
                workflow_id=uuid4(), kind="assessment", title="W",
                state="completed", approval_mode="none",
            ),
            artifacts=(ArtifactRef(stage_key="scheduling", status="approved", revision=2),),
        )
        runs = (RunSummary(run_id=uuid4(), agent_key="grader", status="completed"),)
        engine = ContextEngine(
            providers=[
                FakeProvider("course", course),
                FakeProvider("workflow", workflow),
                FakeProvider("previous_outputs", runs),
            ]
        )
        ctx = await engine.build(_request())
        kinds = [k.kind for k in ctx.knowledge]
        assert kinds.count("material") == 2
        assert kinds.count("artifact") == 1
        assert kinds.count("run") == 1
        artifact_ref = next(k for k in ctx.knowledge if k.kind == "artifact")
        assert artifact_ref.ref_id.endswith(":scheduling")


class TestPureProviders:
    def test_permissions_provider_reflects_matrix_and_registry(self):
        facet = PermissionsProvider().collect(_request(role="teacher"))
        assert "materials.list" in facet.allowed_tools
        assert "exam_generator" in facet.allowed_agents
        student = PermissionsProvider().collect(_request(role="student"))
        assert "materials.list" not in student.allowed_tools
        assert student.allowed_agents == ("student_assistant",)

    def test_academic_policies_derived_from_platform_grading(self):
        policies = AcademicPolicyProvider().collect(_request())
        bands = {b.min_percentage: b.grade for b in policies.grade_bands}
        assert bands[90.0] == "A+"
        assert bands[50.0] == "D"
        assert bands[0.0] == "F"
        assert policies.pass_threshold == 50.0
        assert "pdf" in policies.allowed_material_types


class TestIdentityBridge:
    def test_uuid_or_none_tolerates_garbage(self):
        assert _uuid_or_none(None) is None
        assert _uuid_or_none("not-a-uuid") is None
        value = uuid4()
        assert _uuid_or_none(str(value)) == value
        assert _uuid_or_none(value) == value

    async def test_build_for_identity_reads_extra_hints(self, monkeypatch):
        captured = {}

        class CapturingEngine:
            async def build(self, request):
                captured["request"] = request
                return AgentExecutionContext(request_id=request.request_id, built_at=None, agent_key=request.agent_key)

        import app.ai.context_engine.engine as engine_module

        monkeypatch.setattr(engine_module, "_default_engine", CapturingEngine())
        workflow_id, class_id = uuid4(), uuid4()
        identity = AIRunContext(
            user_id=uuid4(),
            role="teacher",
            extra={"workflow_id": str(workflow_id), "stage": "quality_review", "class_id": str(class_id)},
        )
        snapshot = await build_for_identity(identity, agent_key="grader", session_id="s1")
        request: ContextRequest = captured["request"]
        assert request.workflow_id == workflow_id
        assert request.class_id == class_id
        assert request.stage_key == "quality_review"
        assert request.session_id == "s1"
        assert request.request_id == identity.request_id
        assert isinstance(snapshot, AgentExecutionContext)
