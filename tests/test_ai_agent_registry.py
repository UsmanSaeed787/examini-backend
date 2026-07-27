"""Unit tests for the dynamic Agent Registry (Phase 2): discovery,
versioning, enable/disable, validation, metadata. Uses the in-memory state
backend — no DB required."""
import pytest

from app.ai.agents import registry
from app.ai.agents.definitions import AgentDefinition, ModelOverrides
from app.ai.config import ai_settings
from app.ai.runtime.exceptions import AgentDisabledError, RegistryError
from app.middleware.error_handler import AuthorizationError, NotFoundError


@pytest.fixture(autouse=True)
def memory_state_backend():
    """Swap the DB enable/disable backend for an in-memory one per test."""
    previous = registry.set_state_backend(registry.InMemoryAgentStateBackend())
    yield
    registry.set_state_backend(previous)


@pytest.fixture
def scratch_agent():
    """A throwaway definition registered for the test, removed after."""
    definition = AgentDefinition(
        key="scratch_agent",
        name="Scratch",
        description="test-only",
        factory=lambda: None,
        version="1.0.0",
        allowed_roles=("teacher",),
        required_tools=("exams.list_own",),
    )
    registry.register(definition)
    yield definition
    registry.unregister("scratch_agent")


class TestDiscovery:
    def test_discovers_all_agent_modules(self):
        count = registry.discover(force=True)
        assert count >= 6
        for key in ("exam_generator", "grader", "analytics", "teacher_assistant",
                    "student_assistant", "triage"):
            assert registry.get_spec(key).key == key

    def test_metadata_is_complete(self):
        entries = {e["key"]: e for e in registry.list_all()}
        generator = entries["exam_generator"]
        assert generator["structured_output"] == "GeneratedExamOutput"
        assert "assessment" in generator["supported_workflows"]
        assert generator["api_invocable"] is False
        assert generator["enabled"] is True
        assert "materials.get_text" in generator["required_tools"]
        assert entries["grader"]["capabilities"] == ["grading", "review"]


class TestVersioning:
    def test_latest_wins_and_exact_pin(self, scratch_agent):
        registry.register(
            AgentDefinition(
                key="scratch_agent",
                name="Scratch v1.2",
                description="newer",
                factory=lambda: None,
                version="1.2.0",
                allowed_roles=("teacher",),
            )
        )
        assert registry.get_spec("scratch_agent").version == "1.2.0"
        assert registry.get_spec("scratch_agent", version="1.0.0").name == "Scratch"
        assert registry.versions_of("scratch_agent") == ["1.0.0", "1.2.0"]

    def test_unknown_version_raises(self, scratch_agent):
        with pytest.raises(NotFoundError):
            registry.get_spec("scratch_agent", version="9.9.9")

    def test_duplicate_version_rejected_unless_override(self, scratch_agent):
        clone = AgentDefinition(
            key="scratch_agent",
            name="Clone",
            description="dup",
            factory=lambda: None,
            version="1.0.0",
            allowed_roles=("teacher",),
        )
        with pytest.raises(RegistryError):
            registry.register(clone)
        registry.register(clone, override=True)
        assert registry.get_spec("scratch_agent", version="1.0.0").name == "Clone"


class TestValidation:
    def test_required_tool_not_granted_to_role_fails_registration(self):
        bad = AgentDefinition(
            key="bad_agent",
            name="Bad",
            description="declares a tool its role cannot use",
            factory=lambda: None,
            allowed_roles=("student",),
            required_tools=("materials.get_text",),  # teacher-only capability
        )
        with pytest.raises(RegistryError):
            registry.register(bad)
        assert "bad_agent" not in registry._DEFINITIONS


class TestEnableDisable:
    def test_disable_blocks_resolution_and_listing(self, scratch_agent):
        assert registry.is_enabled("scratch_agent") is True
        registry.set_enabled("scratch_agent", False)
        assert registry.is_enabled("scratch_agent") is False
        with pytest.raises(AgentDisabledError):
            registry.ensure_agent_allowed("scratch_agent", "teacher")
        assert all(d.key != "scratch_agent" for d in registry.list_for_role("teacher"))
        registry.set_enabled("scratch_agent", True)
        assert registry.ensure_agent_allowed("scratch_agent", "teacher").key == "scratch_agent"

    def test_env_hard_off_beats_db_enable(self, scratch_agent, monkeypatch):
        monkeypatch.setattr(ai_settings, "disabled_agents", "scratch_agent, other")
        registry.set_enabled("scratch_agent", True)
        assert registry.is_enabled("scratch_agent") is False

    def test_set_enabled_on_unknown_agent_raises(self):
        with pytest.raises(NotFoundError):
            registry.set_enabled("no_such_agent", True)


class TestResolutionRules:
    def test_role_gate_still_enforced(self, scratch_agent):
        with pytest.raises(AuthorizationError):
            registry.ensure_agent_allowed("scratch_agent", "student")

    def test_version_pin_through_resolution(self, scratch_agent):
        spec = registry.ensure_agent_allowed("scratch_agent", "teacher", version="1.0.0")
        assert spec.version == "1.0.0"

    def test_model_overrides_carried_on_definition(self):
        definition = AgentDefinition(
            key="tuned_agent",
            name="Tuned",
            description="custom model config",
            factory=lambda: None,
            allowed_roles=("teacher",),
            model_overrides=ModelOverrides(model="gemini-2.5-pro", max_turns=4, temperature=0.2),
        )
        registry.register(definition)
        try:
            spec = registry.get_spec("tuned_agent")
            assert spec.model_overrides.model == "gemini-2.5-pro"
            assert spec.model_overrides.max_turns == 4
        finally:
            registry.unregister("tuned_agent")
