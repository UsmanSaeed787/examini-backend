# Agent Registry — Phase 2 of the Educational Agent OS

> Implemented in `backend/app/ai/agents/` (registry + definitions) on top of
> the runtime kernel (`AI_RUNTIME_DESIGN.md`). No business agents were added;
> the six existing agents were migrated onto the new contract.

## 1. What changed

The static, hand-maintained agent list became a **dynamic registry** that can
discover, register, version, enable/disable, and resolve agents — while the
execution path (`runner.execute_run`) kept its signature, so **no workflow
code changed**.

## 2. The contract: `AgentDefinition` (`agents/definitions.py`)

Every agent module publishes one declarative, SDK-free object:

| Field | Meaning |
|---|---|
| `key`, `name`, `description` | identity + human metadata |
| `version` | semver-ish; the registry keeps **every** registered version |
| `factory` | `() -> agents.Agent` (SDK imported lazily inside the module) |
| `allowed_roles` | permissions (same `UserRole` values as the REST layer) |
| `capabilities` | tags for catalog/search (`"grading"`, `"analysis"`, …) |
| `required_tools` | authz capability names the agent's tools use — **validated at registration**: every tool must be granted to every allowed role, so config drift fails fast instead of 403-ing mid-run |
| `supported_workflows` | workflow kinds this agent can serve (links to the kernel's workflow catalog) |
| `structured_output` | declared output model name (e.g. `GeneratedExamOutput`) |
| `uses_session` / `api_invocable` | session memory; whether `POST /api/ai/runs` may invoke it directly |
| `model_overrides` | per-agent `ModelOverrides` (model, max_turns, max_output_tokens, temperature) — honored by `execution.execute_agent`, including per-model OpenAI↔Gemini base-URL re-routing |

## 3. Registry behaviors (`agents/registry.py`)

- **Discovery** — `discover()` scans `app/ai/agents/` with pkgutil; any module
  exposing `DEFINITION` is registered. Adding an agent = adding a file.
  Idempotent, triggered lazily on first use.
- **Versioning** — storage is `key -> {version -> definition}`. `get_spec(key)`
  resolves the highest version; `get_spec(key, version=...)` pins exactly.
  `POST /api/ai/runs` accepts `agent_version` and pins the whole run.
- **Enable/disable** — two layers, env wins:
  1. `AI_DISABLED_AGENTS=grader,analytics` (hard off switch in config);
  2. the `ai_agent_state` table (migration `10` / Alembic `0004`) — toggled at
     runtime via the admin API, shared across workers, records who toggled.
  Disabled agents disappear from role listings and reject execution with
  `AI_AGENT_DISABLED` (403). The persistence is behind a pluggable
  `AgentStateBackend` (DB by default, in-memory for tests).
- **Resolution** — `ensure_agent_allowed(key, role, version)` = exists →
  enabled → role-permitted, used unchanged by the runner and routes.

## 4. API surface (additive)

```
GET  /api/ai/agents                    admin: full metadata incl. disabled, versions
POST /api/ai/agents/{key}/enable       admin
POST /api/ai/agents/{key}/disable      admin
POST /api/ai/runs {agent_version?}     optional exact-version pin per run
```
`GET /api/ai/capabilities` remains the role-scoped listing (now excludes
disabled agents automatically).

## 5. Execution without workflow changes

`runner.execute_run(context, key, input, session_id=None, run_id=None,
version=None)` — the only change is the optional `version`. The runner now
passes the resolved definition into `execution.execute_agent`, which applies
`model_overrides` over the `AISettings` defaults (`provider.build_model`
accepts a per-agent model and re-evaluates provider routing per name).
Facade, background jobs, and `AgentStageHandler` were untouched.

## 6. Adding a future business agent (when its phase comes)

1. Create `app/ai/agents/<name>.py` with `build()` and a `DEFINITION`
   (declare roles, required tools, workflows, structured output, and any
   model overrides).
2. Add its instructions asset in `ai/instructions/<key>.md`.
3. Done — discovery registers it; capabilities/agents endpoints list it;
   `execute_run("<key>", ...)` and `AgentStageHandler(stage, "<key>")` can
   run it; an admin can disable it at any time.
