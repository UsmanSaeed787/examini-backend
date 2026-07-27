"""Dynamic Agent Registry (Phase 2 of the Educational Agent OS).

Discovers, registers, versions, enables/disables, and resolves agents —
without any workflow code changing (runner/routes keep calling the same
functions this module has always exported).

- DISCOVERY: any module in app/ai/agents/ exposing a module-level
  ``DEFINITION: AgentDefinition`` is registered automatically on first use.
  Adding an agent = adding a file; no central list to edit.
- VERSIONING: every (key, version) pair is kept; resolution returns the
  highest version unless an exact version is requested.
- ENABLE/DISABLE: two layers — the AI_DISABLED_AGENTS env list (hard off
  switch) and the ai_agent_state table (runtime toggle via the admin API,
  shared across workers). The DB layer is pluggable (AgentStateBackend) so
  tests run without a database.
- VALIDATION: on registration, every declared required_tool must be granted
  to every allowed role in the authz matrix — config drift fails fast
  instead of 403-ing mid-run.
"""
import importlib
import pkgutil
from typing import Dict, List, Optional, Protocol

from app.ai.agents.definitions import AgentDefinition, AgentSpec  # noqa: F401 (AgentSpec re-export)
from app.ai.config import ai_settings
from app.ai.policies.authz import is_tool_allowed
from app.ai.runtime.exceptions import AgentDisabledError, RegistryError
from app.middleware.error_handler import AuthorizationError, NotFoundError

_NON_AGENT_MODULES = {"registry", "definitions"}


# ---------------------------------------------------------------- state backend

class AgentStateBackend(Protocol):
    def get(self, agent_key: str) -> Optional[bool]: ...
    def get_all(self) -> Dict[str, bool]: ...
    def set(self, agent_key: str, enabled: bool, actor_id) -> None: ...


class DBAgentStateBackend:
    def get(self, agent_key: str) -> Optional[bool]:
        from app.ai.persistence import store

        return store.get_agent_enabled(agent_key)

    def get_all(self) -> Dict[str, bool]:
        from app.ai.persistence import store

        return store.get_agent_states()

    def set(self, agent_key: str, enabled: bool, actor_id) -> None:
        from app.ai.persistence import store

        store.set_agent_enabled(agent_key, enabled, actor_id)


class InMemoryAgentStateBackend:
    """For tests and SDK-less environments."""

    def __init__(self) -> None:
        self._states: Dict[str, bool] = {}

    def get(self, agent_key: str) -> Optional[bool]:
        return self._states.get(agent_key)

    def get_all(self) -> Dict[str, bool]:
        return dict(self._states)

    def set(self, agent_key: str, enabled: bool, actor_id) -> None:
        self._states[agent_key] = enabled


_state_backend: AgentStateBackend = DBAgentStateBackend()


def set_state_backend(backend: AgentStateBackend) -> AgentStateBackend:
    """Swap the enable/disable persistence (returns the previous backend)."""
    global _state_backend
    previous = _state_backend
    _state_backend = backend
    return previous


# ---------------------------------------------------------------- registry core

# key -> {version -> definition}
_DEFINITIONS: Dict[str, Dict[str, AgentDefinition]] = {}
_discovered = False


def register(definition: AgentDefinition, *, override: bool = False) -> None:
    """Register one agent definition (validated). Same (key, version) twice
    is an error unless override=True.

    required_tools are resolved through the Tool Registry: each key must be a
    registered tool whose permission is granted to every allowed role."""
    from app.ai.tools import registry as tool_registry

    for tool_key in definition.required_tools:
        tool_def = tool_registry.get_optional(tool_key)
        if tool_def is None:
            raise RegistryError(
                f"Agent '{definition.key}' requires unknown tool '{tool_key}'"
            )
        for role in definition.allowed_roles:
            if not is_tool_allowed(role, tool_def.permission):
                raise RegistryError(
                    f"Agent '{definition.key}' requires tool '{tool_key}' "
                    f"(permission '{tool_def.permission}') which role '{role}' "
                    "is not granted in the authz matrix"
                )
    versions = _DEFINITIONS.setdefault(definition.key, {})
    if definition.version in versions and not override:
        raise RegistryError(
            f"Agent '{definition.key}' version '{definition.version}' is already registered"
        )
    versions[definition.version] = definition


def unregister(agent_key: str, version: Optional[str] = None) -> None:
    if version is None:
        _DEFINITIONS.pop(agent_key, None)
    else:
        _DEFINITIONS.get(agent_key, {}).pop(version, None)


def discover(force: bool = False) -> int:
    """Import every module in app/ai/agents/ and register its DEFINITION.
    Idempotent; returns the number of registered agent keys."""
    global _discovered
    if _discovered and not force:
        return len(_DEFINITIONS)
    import app.ai.agents as agents_pkg

    for module_info in pkgutil.iter_modules(agents_pkg.__path__):
        name = module_info.name
        if name.startswith("_") or name in _NON_AGENT_MODULES:
            continue
        module = importlib.import_module(f"app.ai.agents.{name}")
        definition = getattr(module, "DEFINITION", None)
        if isinstance(definition, AgentDefinition):
            register(definition, override=True)
    _discovered = True
    return len(_DEFINITIONS)


def get_spec(agent_key: str, version: Optional[str] = None) -> AgentDefinition:
    """Resolve an agent: exact version if given, else the latest."""
    discover()
    versions = _DEFINITIONS.get(agent_key)
    if not versions:
        raise NotFoundError(f"Unknown agent '{agent_key}'")
    if version is not None:
        definition = versions.get(version)
        if definition is None:
            raise NotFoundError(f"Agent '{agent_key}' has no version '{version}'")
        return definition
    return max(versions.values(), key=lambda d: d.version_tuple())


def versions_of(agent_key: str) -> List[str]:
    discover()
    return sorted(
        (d.version for d in _DEFINITIONS.get(agent_key, {}).values()),
        key=lambda v: get_spec(agent_key, v).version_tuple(),
    )


# ---------------------------------------------------------------- enablement

def is_enabled(agent_key: str) -> bool:
    """env hard-off list wins; then the state backend; default enabled."""
    env_disabled = {
        item.strip() for item in (ai_settings.disabled_agents or "").split(",") if item.strip()
    }
    if agent_key in env_disabled:
        return False
    flag = _state_backend.get(agent_key)
    return True if flag is None else flag


def set_enabled(agent_key: str, enabled: bool, actor_id=None) -> None:
    get_spec(agent_key)  # NotFoundError on unknown keys
    _state_backend.set(agent_key, enabled, actor_id)


# ---------------------------------------------------------------- resolution API
# (stable surface used by runner.py, routes.py, and tests — pre-Phase-2 names)

def ensure_agent_allowed(
    agent_key: str, role: str, version: Optional[str] = None
) -> AgentDefinition:
    definition = get_spec(agent_key, version)
    if not is_enabled(agent_key):
        raise AgentDisabledError(f"Agent '{agent_key}' is currently disabled")
    if role not in definition.allowed_roles:
        raise AuthorizationError(f"Role '{role}' may not use agent '{agent_key}'")
    return definition


def list_for_role(role: str, api_only: bool = True) -> List[AgentDefinition]:
    discover()
    results = []
    for key in sorted(_DEFINITIONS.keys()):
        definition = get_spec(key)
        if role not in definition.allowed_roles:
            continue
        if api_only and not definition.api_invocable:
            continue
        if not is_enabled(key):
            continue
        results.append(definition)
    return results


def list_all() -> List[dict]:
    """Full metadata for every registered agent (admin surface)."""
    discover()
    entries = []
    for key in sorted(_DEFINITIONS.keys()):
        definition = get_spec(key)
        overrides = definition.model_overrides
        entries.append(
            {
                "key": definition.key,
                "name": definition.name,
                "description": definition.description,
                "version": definition.version,
                "versions": versions_of(key),
                "allowed_roles": list(definition.allowed_roles),
                "capabilities": list(definition.capabilities),
                "required_tools": list(definition.required_tools),
                "supported_workflows": list(definition.supported_workflows),
                "structured_output": definition.structured_output,
                "uses_session": definition.uses_session,
                "api_invocable": definition.api_invocable,
                "enabled": is_enabled(key),
                "model_overrides": {
                    "model": overrides.model,
                    "max_turns": overrides.max_turns,
                    "max_output_tokens": overrides.max_output_tokens,
                    "temperature": overrides.temperature,
                }
                if overrides
                else None,
            }
        )
    return entries
