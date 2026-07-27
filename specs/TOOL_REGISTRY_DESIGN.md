# Tool Registry — Phase 3 of the Educational Agent OS

> Implemented in `backend/app/ai/tools/registry.py` plus the migrated tool
> modules. Companion to `AGENT_REGISTRY_DESIGN.md` (Phase 2) and
> `AI_RUNTIME_DESIGN.md` (kernel). No business logic was duplicated — every
> tool wraps an existing service or a read-only query; agents never touch
> SQLAlchemy or the database.

## 1. What changed

The tool layer's ad-hoc `@function_tool` wrappers became a **Tool Registry**:
every agent-visible capability is a declarative `ToolDefinition` with a
Pydantic input contract, an authz permission, service metadata, and one shared
execution pipeline. Agents now resolve tools **by key** from the registry
(`sdk_tools("materials.list", ...)`) instead of importing implementation
modules — `required_tools` on an `AgentDefinition` is the single source of
truth for what an agent can touch.

## 2. The contract: `ToolDefinition`

| Field | Meaning |
|---|---|
| `key` | unique tool id (`materials.list`); SDK name is the dot→underscore form |
| `description` | what the LLM reads |
| `impl` | sync callable `(ToolContext, params) -> data` — the only place services are called |
| `permission` | authz capability checked per call (defaults to `key`; e.g. both workflow tools share `workflow.read`) |
| `params_model` | Pydantic input model → JSON schema for the LLM + server-side validation |
| `services` / `tags` | metadata: which backend services it wraps, catalog tags |

Registration (via the `@tool` decorator) **fails fast** if the permission is
granted to no role in `policies/authz.py` — a typo can't create an
unreachable tool.

## 3. Execution pipeline (one path for every call)

```
LLM tool call (args JSON)
  → authz: ensure_tool_allowed(role, permission)      raises 403 — not model-recoverable
  → validation: params_model.model_validate_json      bad args → {"error": "InvalidArguments"} (model retries)
  → DI: ToolContext(identity, ToolDependencies)       injected session factory (swappable in tests)
  → asyncio.to_thread(impl, ctx, params)              services run off the event loop
  → kernel tracing: span("tool", key)                 tool.started/completed/failed events + duration metrics
  → domain errors (NotFound/Validation/Authorization/ValueError)
        → {"error": ..., "message": ...}              model-readable, run survives
```

## 4. Registry behaviors

- **Discovery** — importing every module in `app/ai/tools/` runs the `@tool`
  registrations. Adding a tool = adding a decorated function.
- **Permissions** — role coverage is *derived* from the authz matrix
  (`allowed_roles()`), never declared twice.
- **DI** — `ToolDependencies` (currently the DB session scope) is injected
  per call and swappable via `set_dependencies()`; the pipeline tests run
  with a fake session factory and no database.
- **SDK bridge** — `sdk_tools(*keys)` builds cached `FunctionTool` objects
  (non-strict JSON schema for Gemini compatibility) whose `on_invoke` is the
  pipeline above.
- **Cross-registry validation** — the Agent Registry now resolves each
  agent's `required_tools` through this registry at registration: unknown
  tool keys or permissions not granted to every allowed role are
  `RegistryError`s at startup, not 403s mid-run.

## 5. Current catalog (14 tools)

`materials.list`, `materials.get_text` (MaterialService/ParserService) ·
`exams.list_own`, `exams.get_overview` (ExamService) ·
`results.list_for_exam`, `results.pending_text_answers`, `results.my_results` ·
`students.my_enrollments`, `students.my_upcoming_exams` ·
`question_bank.save`, `question_bank.list` (QuestionBankService) ·
`notifications.send` (NotificationService) ·
`workflow.get_assessment_workflow`, `workflow.get_stage_artifact`
(assessment workflow store; shared permission `workflow.read`).

Admin introspection: `GET /api/ai/tools` — keys, permissions, role coverage,
wrapped services, and the exact JSON schema each tool exposes to the model.

## 6. Adding a tool for a future capability

1. Add the domain logic to a **service** (or reuse an existing one).
2. Write one decorated function in a module under `app/ai/tools/`:
   `@tool(key=..., description=..., params=ParamsModel, services=(...))`.
3. Grant the permission to the right roles in `policies/authz.py`.
4. Reference the key in an agent's `REQUIRED_TOOLS`/`required_tools`.
Discovery, validation, listing, tracing, and execution all apply automatically.
