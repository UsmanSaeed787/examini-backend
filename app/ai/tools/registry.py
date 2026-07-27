"""Tool Registry (Phase 3 of the Educational Agent OS).

Every agent-visible capability is a registered ToolDefinition wrapping an
existing backend service. Agents never touch SQLAlchemy or the DB — they
receive SDK FunctionTools built here, and every invocation flows through ONE
pipeline:

    authz (role x permission) -> input validation (Pydantic) ->
    dependency injection (ToolContext) -> off-thread service call ->
    kernel tracing (tool.* events + metrics) -> error mapping

- REGISTRATION: implementations use the @tool decorator; discovery imports
  every module in app/ai/tools/ so adding a tool = adding a function.
- PERMISSIONS: each tool maps to an authz capability (`permission`,
  defaulting to its key) checked against policies/authz.py on every call;
  registration fails fast if the permission exists in no role's matrix row.
- VALIDATION: each tool declares a Pydantic params model; the model's JSON
  schema is what the LLM sees, and arguments are validated before any
  service is called. Bad arguments come back as a model-readable error, not
  a crashed run.
- DEPENDENCY INJECTION: impls get a ToolContext (identity + ToolDependencies);
  the DB session factory is injected and swappable (tests run without a DB).
"""
import asyncio
import importlib
import pkgutil
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple, Type

from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from app.ai.context import AIRunContext
from app.ai.policies.authz import TOOL_CAPABILITIES, ensure_tool_allowed
from app.ai.runtime.exceptions import RegistryError
from app.ai.runtime.tracing import span
from app.middleware.error_handler import (
    AuthorizationError,
    NotFoundError,
    ValidationError,
)

_NON_TOOL_MODULES = {"registry", "_base"}


# ---------------------------------------------------------------- DI

@dataclass
class ToolDependencies:
    """Injected infrastructure. Defaults to the app's real session factory;
    tests swap it via set_dependencies()."""

    session_scope: Callable = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.session_scope is None:
            from app.ai.tools._base import db_session

            self.session_scope = db_session


_dependencies = ToolDependencies()


def set_dependencies(deps: ToolDependencies) -> ToolDependencies:
    """Swap the injected dependencies (returns the previous set)."""
    global _dependencies
    previous = _dependencies
    _dependencies = deps
    return previous


@dataclass
class ToolContext:
    """What every tool impl receives: WHO is calling + injected deps."""

    identity: AIRunContext
    deps: ToolDependencies

    def db(self):
        """Open a scoped DB session (context manager)."""
        return self.deps.session_scope()


# ---------------------------------------------------------------- definition

@dataclass(frozen=True)
class ToolDefinition:
    key: str                                   # unique tool id, e.g. "materials.list"
    description: str                           # what the LLM reads
    impl: Callable[[ToolContext, Optional[BaseModel]], Any]  # sync, service-backed
    permission: str                            # authz capability (defaults to key)
    params_model: Optional[Type[BaseModel]] = None
    services: Tuple[str, ...] = ()             # wrapped services (metadata)
    tags: Tuple[str, ...] = ()

    @property
    def sdk_name(self) -> str:
        return self.key.replace(".", "_")

    def allowed_roles(self) -> List[str]:
        return sorted(
            role for role, caps in TOOL_CAPABILITIES.items() if self.permission in caps
        )


_TOOLS: Dict[str, ToolDefinition] = {}
_SDK_CACHE: Dict[str, Any] = {}
_discovered = False


def register(definition: ToolDefinition, *, override: bool = False) -> None:
    if not definition.allowed_roles():
        raise RegistryError(
            f"Tool '{definition.key}' permission '{definition.permission}' is not "
            "granted to any role in the authz matrix"
        )
    if definition.key in _TOOLS and not override:
        raise RegistryError(f"Tool '{definition.key}' is already registered")
    _TOOLS[definition.key] = definition
    _SDK_CACHE.pop(definition.key, None)


def unregister(key: str) -> None:
    _TOOLS.pop(key, None)
    _SDK_CACHE.pop(key, None)


def tool(
    *,
    key: str,
    description: str,
    permission: Optional[str] = None,
    params: Optional[Type[BaseModel]] = None,
    services: Tuple[str, ...] = (),
    tags: Tuple[str, ...] = (),
):
    """Decorator: registers the wrapped impl as a ToolDefinition."""

    def decorator(impl):
        register(
            ToolDefinition(
                key=key,
                description=description,
                impl=impl,
                permission=permission or key,
                params_model=params,
                services=services,
                tags=tags,
            ),
            override=True,  # module re-imports (tests) stay idempotent
        )
        return impl

    return decorator


def discover(force: bool = False) -> int:
    """Import every module in app/ai/tools/ so @tool registrations run."""
    global _discovered
    if _discovered and not force:
        return len(_TOOLS)
    import app.ai.tools as tools_pkg

    for module_info in pkgutil.iter_modules(tools_pkg.__path__):
        name = module_info.name
        if name.startswith("__") or name in _NON_TOOL_MODULES:
            continue
        importlib.import_module(f"app.ai.tools.{name}")
    _discovered = True
    return len(_TOOLS)


def get(key: str) -> ToolDefinition:
    discover()
    definition = _TOOLS.get(key)
    if definition is None:
        raise NotFoundError(f"Unknown tool '{key}'")
    return definition


def get_optional(key: str) -> Optional[ToolDefinition]:
    discover()
    return _TOOLS.get(key)


def list_all() -> List[dict]:
    """Full metadata for every registered tool (admin surface)."""
    discover()
    return [
        {
            "key": d.key,
            "sdk_name": d.sdk_name,
            "description": d.description,
            "permission": d.permission,
            "allowed_roles": d.allowed_roles(),
            "services": list(d.services),
            "tags": list(d.tags),
            "params_schema": d.params_model.model_json_schema() if d.params_model else None,
            "module": d.impl.__module__,
        }
        for _, d in sorted(_TOOLS.items())
    ]


def list_for_role(role: str) -> List[ToolDefinition]:
    discover()
    return [d for _, d in sorted(_TOOLS.items()) if role in d.allowed_roles()]


# ---------------------------------------------------------------- pipeline

async def execute_tool(definition: ToolDefinition, identity: AIRunContext, args_json: str) -> Any:
    """The single execution pipeline every tool call goes through."""
    ensure_tool_allowed(identity.role, definition.permission)  # raises 403 — not model-recoverable

    params: Optional[BaseModel] = None
    if definition.params_model is not None:
        try:
            params = definition.params_model.model_validate_json(args_json or "{}")
        except PydanticValidationError as exc:
            return {"error": "InvalidArguments", "message": str(exc)[:500]}

    try:
        async with span(
            "tool",
            stage_key=definition.key,
            run_id=identity.run_id,
            user_id=identity.user_id,
        ):
            return await asyncio.to_thread(
                definition.impl, ToolContext(identity=identity, deps=_dependencies), params
            )
    except (NotFoundError, ValidationError, AuthorizationError) as exc:
        # Domain failure the model can react to (adjust and retry).
        return {"error": exc.__class__.__name__, "message": str(exc)}
    except ValueError as exc:
        # Bad identifiers etc. that slipped past schema validation.
        return {"error": "InvalidArguments", "message": str(exc)[:500]}


# ---------------------------------------------------------------- SDK bridge

def sdk_tools(*keys: str) -> List[Any]:
    """Resolve tool keys into SDK FunctionTool objects (cached). This is what
    agent factories call — agents never import tool implementation modules."""
    discover()
    resolved = []
    for key in keys:
        definition = get(key)
        cached = _SDK_CACHE.get(key)
        if cached is None:
            cached = _build_sdk_tool(definition)
            _SDK_CACHE[key] = cached
        resolved.append(cached)
    return resolved


def _build_sdk_tool(definition: ToolDefinition):
    from agents import FunctionTool

    async def on_invoke(ctx, args_json: str):
        return await execute_tool(definition, ctx.context, args_json)

    schema = (
        definition.params_model.model_json_schema()
        if definition.params_model
        else {"type": "object", "properties": {}, "additionalProperties": False}
    )
    return FunctionTool(
        name=definition.sdk_name,
        description=definition.description,
        params_json_schema=schema,
        on_invoke_tool=on_invoke,
        # non-strict: keeps schemas Gemini-OpenAI-compat friendly
        strict_json_schema=False,
    )
