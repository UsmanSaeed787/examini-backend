"""AgentDefinition — the declarative contract every agent module publishes.

A module in app/ai/agents/ becomes registerable by exposing a module-level
``DEFINITION: AgentDefinition``. The registry discovers it; nothing else
needs editing (no central list, no workflow changes). SDK-free on purpose —
importing this module must never pull the openai-agents package.
"""
from dataclasses import dataclass, field
from typing import Callable, Optional, Tuple


@dataclass(frozen=True)
class ModelOverrides:
    """Per-agent model configuration. None = inherit AISettings/platform."""

    model: Optional[str] = None              # e.g. "gemini-2.5-pro" for a heavier agent
    max_turns: Optional[int] = None
    max_output_tokens: Optional[int] = None
    temperature: Optional[float] = None


@dataclass(frozen=True)
class AgentDefinition:
    """Everything the OS knows about an agent without building it."""

    key: str                                  # stable identifier, e.g. "grader"
    name: str                                 # human-readable
    description: str
    factory: Callable[[], "object"]           # -> agents.Agent (lazy SDK import inside)
    version: str = "1.0.0"                    # semver-ish; registry keeps every version
    allowed_roles: Tuple[str, ...] = ()       # permissions (UserRole values)
    capabilities: Tuple[str, ...] = ()        # tags, e.g. ("generation", "analysis")
    required_tools: Tuple[str, ...] = ()      # authz capability names the agent's tools use
    supported_workflows: Tuple[str, ...] = () # workflow kinds this agent can serve as a stage for
    structured_output: Optional[str] = None   # output model name, e.g. "GeneratedExamOutput"
    uses_session: bool = False
    api_invocable: bool = True                # invocable via POST /api/ai/runs
    model_overrides: Optional[ModelOverrides] = None

    def version_tuple(self) -> Tuple[int, ...]:
        parts = []
        for chunk in self.version.split("."):
            digits = "".join(c for c in chunk if c.isdigit())
            parts.append(int(digits) if digits else 0)
        return tuple(parts) or (0,)


# Backward-compatible alias (pre-Phase-2 code referred to AgentSpec).
AgentSpec = AgentDefinition
