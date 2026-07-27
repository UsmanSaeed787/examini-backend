"""Generic typed registries + the capability catalog.

Registry[T] is the one registration primitive for anything keyed by a stable
string (workflow kinds today; tool packs, model routes, policies tomorrow).
The agent registry (agents/registry.py) predates this and keeps its
role-gating specifics; new registries should be built on Registry[T]."""
from dataclasses import dataclass, field
from typing import Dict, Generic, List, Tuple, TypeVar

from app.ai.runtime.exceptions import RegistryError
from app.middleware.error_handler import NotFoundError

T = TypeVar("T")


class Registry(Generic[T]):
    def __init__(self, kind: str):
        self.kind = kind
        self._items: Dict[str, T] = {}

    def register(self, key: str, item: T, *, override: bool = False) -> None:
        if key in self._items and not override:
            raise RegistryError(f"{self.kind} '{key}' is already registered")
        self._items[key] = item

    def get(self, key: str) -> T:
        item = self._items.get(key)
        if item is None:
            raise NotFoundError(f"Unknown {self.kind} '{key}'")
        return item

    def keys(self) -> List[str]:
        return sorted(self._items.keys())

    def items(self) -> List[Tuple[str, T]]:
        return sorted(self._items.items())

    def __contains__(self, key: str) -> bool:
        return key in self._items


@dataclass(frozen=True)
class WorkflowDefinition:
    """Catalog entry for a workflow-shaped capability. Metadata only — the
    capability owns its orchestration; the kernel only needs to enumerate."""

    kind: str
    title: str
    stage_keys: Tuple[str, ...]
    description: str = ""
    allowed_roles: Tuple[str, ...] = field(default_factory=tuple)


workflow_registry: Registry[WorkflowDefinition] = Registry("workflow")
