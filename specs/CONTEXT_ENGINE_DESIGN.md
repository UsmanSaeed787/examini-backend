# Context Engine — Phase 4 of the Educational Agent OS

> Implemented in `backend/app/ai/context_engine/`. Companion to the kernel
> (`AI_RUNTIME_DESIGN.md`) and the two registries (Phases 2–3). Pure data
> assembly: **no LLM logic exists here** — rendering a context into prompt
> text is a consumer concern, deliberately out of scope.

## 1. What it does

Before an agent runs, the engine assembles one **strongly typed, immutable**
snapshot — `AgentExecutionContext` — and attaches it to the run identity
(`AIRunContext.snapshot`). Tools, guardrails, and future context-aware
consumers read it; nothing can mutate it (frozen dataclasses, tuples,
`MappingProxyType` for dict-shaped data).

## 2. The facets (all collected from real platform state)

| Facet | Model | Source |
|---|---|---|
| Authenticated user | `UserContext` | `users` table |
| Permissions | `PermissionsContext` | authz matrix (allowed tools) + Agent Registry (allowed agents) |
| Current workflow | `WorkflowContext` | `ai_workflows` (owner-scoped) |
| Current stage | `StageInfo` | `ai_workflow_stages` (via the `stage` hint) |
| Artifacts | `ArtifactRef` tuple | all produced stage artifacts of the workflow |
| Conversation history | `ConversationContext` | `ai_messages` session store (trimmed to `AI_CONTEXT_HISTORY_LIMIT`) |
| Institution settings | `InstitutionContext` | app settings (name, version, debug) |
| Academic policies | `AcademicPolicies` | **derived by probing** the platform's own `calculate_grade()` (grade bands, pass threshold — zero duplication) + upload rules + exam caps |
| Course information | `CourseContext` | `classes`/`sections`/`materials` (role-scoped: teachers see their own materials) |
| Previous outputs | `RunSummary` tuple | last N completed `ai_runs` for this user/agent |
| Knowledge references | `KnowledgeReference` tuple | composed across facets: course materials, workflow artifacts, prior runs — **references only**; payloads stay behind authz'd tools |

Plus `warnings: tuple[str, ...]` — a facet provider that fails becomes a
warning entry with a `None` facet, never an exception: **context collection
can never kill a run** (guarded again in the runner, belt-and-suspenders).

## 3. Architecture

```
ContextRequest (user_id, role, agent_key?, session_id?, workflow_id?, stage_key?, class_id?)
        │
        ▼
ContextEngine.build()  ── one worker-thread pass over ContextProviders ──▶ facets
        │                                                                    │
        ▼                                                                    ▼
_compose_knowledge(facets)                                    AgentExecutionContext (frozen)
```

- **Providers** (`providers.py`): 8 built-ins, each a small class with
  `facet` + synchronous `collect(request)`. Read-only; heavy imports are
  lazy; DB reads use the shared session scope.
- **Extension point**: `register_provider()` replaces a same-facet provider
  or appends a new one — how Student Success / Career Intelligence add their
  facets without touching the engine or existing consumers.
- **Optional ids switch facets off**: no `workflow_id` → no workflow/stage/
  artifact facets; no `class_id` → no course facet.

## 4. Integration

- `runner.execute_run` builds the snapshot pre-flight (after the run record,
  before execution) when `AI_CONTEXT_ENGINE_ENABLED=true` (default).
- Hints travel in `AIRunContext.extra`: the facade sets `class_id` for
  generation runs; `AgentStageHandler` already sets `workflow_id` + `stage`
  for agent-backed workflow stages — `build_for_identity()` picks them up
  (tolerating malformed ids).
- Settings: `AI_CONTEXT_ENGINE_ENABLED`, `AI_CONTEXT_HISTORY_LIMIT` (20),
  `AI_CONTEXT_PREVIOUS_RUNS_LIMIT` (5).

## 5. Consumption contract

`ctx.identity.snapshot` (in tools via `ToolContext.identity.snapshot`, in
guardrails via `ctx.context.snapshot`) — typed reads only, e.g.
`snapshot.policies.pass_threshold`, `snapshot.course.materials`,
`snapshot.artifacts[0].artifact["total_questions"]`. Consumers must treat a
facet being `None` as "not applicable/unavailable" and proceed.
