# Examini — AI Operating Layer Design (`backend/app/ai`)

> Architecture design only. No business logic, no prompts, no implementation. Companion to `REPORT.md` (the audit / System of Record). The goal: an extensible AI layer, built on the **OpenAI Agents SDK**, that **orchestrates the existing services** (`ExamService`, `MaterialService`, `ParserService`, `StudentService`, `ResultService`-domain, `StorageService`) rather than replacing them. The current architecture — routers → services → models/schemas, `api/deps.py` RBAC, `middleware/error_handler.py` envelopes — is preserved untouched.

---

## 1. Design Principles

1. **Orchestrate, never re-implement.** The AI layer holds *zero* domain logic. Every read/write of Examini data goes through an existing service, wrapped as an SDK **function tool**. If a capability needs domain logic that doesn't exist yet (e.g., "persist a review score"), that logic is added to the *service layer* first, then wrapped — never written inside `ai/`.
2. **One-way dependency.** `app/ai/*` may import `app/services`, `app/models`, `app/schemas`, `app/utils`, `app/config`. **Nothing outside `ai/` imports from inside `ai/`** except two sanctioned entry points: `ai.api.router` (mounted in `main.py`) and `ai.facade` (called by existing routes that migrate onto the layer). Services never know AI exists.
3. **Tools are the only boundary that touches the app.** Agents see tools; tools see services. An agent definition can never import a service, a model, or the DB session. This makes every agent testable against fake tools and every tool testable without a model.
4. **Authorization is enforced below the model, not by the model.** The current user and role travel in the run context; every tool re-checks permissions via the same rules the REST routes use (`UserRole`, ownership/enrollment checks). A prompt-injected model can only ever do what the calling user could already do through the existing API.
5. **Async-native, non-blocking.** The Agents SDK is async. All wrapped services are synchronous (audit §17), so the tool layer is the single place where sync work is pushed off the event loop (`asyncio.to_thread` / threadpool). This also fixes the existing generation endpoint's loop-blocking as a side effect of migration.
6. **Provider-agnostic via the existing convention.** The platform already switches OpenAI ↔ Gemini by model-name prefix on one `base_url` (audit §12). The AI layer centralizes that logic in **one** provider module; nothing else may construct a client.
7. **Every run is observable and budgeted.** Runs are recorded (tokens, cost, duration, tools called, outcome) and subject to per-user/per-role quotas — closing the audit's "unbounded LLM spend" finding for everything the layer owns.

---

## 2. Package Structure

```
backend/app/ai/
├── __init__.py                 # exports: facade, router — the ONLY public surface
├── facade.py                   # sync-looking entry points for existing routes (strangler seam)
├── config.py                   # AISettings (pydantic-settings, AI_* env vars), feature flags
├── context.py                  # AIRunContext: user, role, db-session factory, request metadata, budget handle
│
├── runtime/                    # OpenAI Agents SDK wiring — the only place SDK plumbing lives
│   ├── provider.py             # single AsyncOpenAI client factory + ModelProvider (OpenAI / Gemini base_url routing)
│   ├── runner.py               # thin wrapper over agents.Runner: run config, max_turns, timeouts, cancellation
│   ├── sessions.py             # Session storage adapter (SDK session protocol → DB-backed conversation state)
│   ├── tracing.py              # TracingProcessor(s): usage/cost capture → run store; optional export
│   └── errors.py               # maps SDK/tool/provider failures → existing middleware exception types
│
├── agents/                     # agent DEFINITIONS only (name, model settings, tool list, handoffs, output type)
│   ├── registry.py             # declarative registry: agent key → factory; capability discovery
│   ├── triage.py               # front-door agent; hands off to specialists (SDK handoffs)
│   ├── exam_generator.py       # generation specialist (replaces the OpenAIService call path)
│   ├── grader.py               # short/long-answer review specialist
│   ├── analytics.py            # results/item-analysis specialist (read-only tools)
│   ├── teacher_assistant.py    # exam-authoring/material-QA specialist
│   └── student_assistant.py    # study-guidance specialist (strictly read-only, own-data tools)
│
├── instructions/               # instruction/prompt ASSETS as data (versioned files), loaded by agents/
│   └── (one file per agent; content out of scope for this design)
│
├── tools/                      # function tools wrapping existing services — the orchestration boundary
│   ├── _base.py                # tool decorator wrapper: context injection, authz check, to_thread, error mapping
│   ├── materials.py            # → MaterialService, ParserService, StorageService (list/get/extract_text)
│   ├── exams.py                # → ExamService (create/get/update/publish; question CRUD)
│   ├── results.py              # → results queries + (new service method) persist review/feedback
│   ├── students.py             # → StudentService (scoped reads: enrollment, own results)
│   ├── question_bank.py        # → (new service methods over existing question_bank table)
│   └── notifications.py        # → (new service methods over existing notifications table)
│
├── guardrails/                 # SDK input/output guardrails — validation, not business logic
│   ├── input.py                # request-shape/limits checks (e.g., question_config sanity, material count caps)
│   ├── output.py               # structured-output conformance (counts, enum vocab, ≥1 correct option per MCQ)
│   └── safety.py               # role-appropriateness / data-boundary checks on final output
│
├── policies/                   # cross-cutting enforcement, independent of any agent
│   ├── authz.py                # capability matrix: (role, tool) → allow/deny + row-scope rules
│   └── quotas.py               # per-user/role run + token budgets; enforced in runner before dispatch
│
├── schemas/                    # Pydantic contracts owned by the AI layer
│   ├── requests.py             # /api/ai request DTOs
│   ├── responses.py            # /api/ai response DTOs (run status, results, streaming events)
│   ├── outputs.py              # agent structured-output types (SDK output_type targets)
│   └── runs.py                 # run/usage records
│
├── persistence/                # AI-owned storage (new migration 08; additive only)
│   ├── models.py               # ai_runs, ai_messages, ai_usage (SQLAlchemy, same Base)
│   └── store.py                # run store: create/update run rows, session state backing
│
├── jobs/                       # execution modes
│   ├── inline.py               # await-in-request (short runs)
│   └── background.py           # FastAPI BackgroundTasks adapter now; queue adapter later (same interface)
│
└── api/                        # thin FastAPI surface, mounted at /api/ai in main.py
    ├── deps.py                 # reuses app.api.deps role guards; builds AIRunContext
    └── routes.py               # POST /api/ai/runs, GET /api/ai/runs/{id}, capability listing, (SSE stream)
```

---

## 3. Module Responsibilities & SDK Mapping

| Module | Responsibility | OpenAI Agents SDK concept |
|---|---|---|
| `runtime/provider.py` | The **only** constructor of model clients. Reads `OPENAI_API_KEY`/`OPENAI_MODEL` (+ new optional `AI_*` overrides); applies the existing `gemini*` → Google OpenAI-compat `base_url` rule; sets `max_tokens`/timeout defaults the current code lacks. | `AsyncOpenAI`, `OpenAIChatCompletionsModel` / `ModelProvider`, `ModelSettings` |
| `runtime/runner.py` | Executes an agent for a context: resolves agent from registry, applies quotas (pre-flight), `max_turns`, wall-clock timeout, cancellation; returns/streams results; records the run. | `Runner.run` / `Runner.run_streamed`, `RunConfig` |
| `runtime/sessions.py` | Conversation continuity for assistant-style agents; persists via `persistence/store.py`. Stateless one-shot runs (generation) skip it. | `Session` protocol |
| `runtime/tracing.py` | Captures spans, token usage, tool calls per run; writes to `ai_usage`; the seam where the unused `audit_logs` table gains its first producer. | `TracingProcessor`, `add_trace_processor` |
| `runtime/errors.py` | Translates SDK exceptions (guardrail tripwires, max-turns, provider errors) into the app's existing exception types so `/api/ai` responses use the standard error envelope — never raw provider text (closes an audit finding for this surface). | `AgentsException`, `InputGuardrailTripwireTriggered`, … |
| `agents/*` | Pure declarations: name, instructions (loaded from `instructions/`), tool list, handoffs, `output_type`, model settings override. No I/O, no imports from `services/`. | `Agent`, `handoff`, `output_type` |
| `agents/registry.py` | Maps stable string keys (`"exam_generator"`, `"triage"`, …) to agent factories; declares which roles may invoke which agent; feeds the capability-listing endpoint. | — (layer-owned) |
| `tools/_base.py` | The keystone. A wrapper around the SDK's tool decorator that: (1) injects `AIRunContext`; (2) runs `policies/authz` for the (role, tool) pair; (3) executes the wrapped sync service call in a worker thread; (4) opens/closes a DB session per invocation; (5) maps service exceptions to tool errors the model can react to. | `@function_tool`, `RunContextWrapper` |
| `tools/*.py` | One module per domain. Each tool = thin adapter: validate args (Pydantic), call one service method, return a serializable result. Argument/return schemas live in `schemas/`. | `@function_tool` |
| `guardrails/*` | Input guardrails reject malformed/oversized requests before the model runs (e.g., inconsistent `question_config` — currently unvalidated, audit §12). Output guardrails verify structured outputs (requested counts honored, enum vocabulary valid, every MCQ has ≥1 correct option — all currently-unverified failure modes). | `@input_guardrail`, `@output_guardrail` |
| `policies/authz.py` | Static capability matrix + row-scope predicates, reusing `UserRole` and the same ownership/enrollment rules services already apply. Deny-by-default: a tool absent from a role's matrix row cannot be called by that role's runs. | — (enforced in `tools/_base.py`) |
| `policies/quotas.py` | Per-user and per-role budgets (runs/day, tokens/run, tokens/day) checked in `runner.py` pre-flight and debited from `tracing` post-run. | — |
| `schemas/outputs.py` | Typed agent outputs (e.g., a generated-exam structure mirroring `ExamCreate`) so parsing is schema-enforced instead of the current tolerant hand-parsing. | `output_type` (structured outputs) |
| `persistence/*` | `ai_runs` (id, user, agent key, status, timings), `ai_messages` (session history), `ai_usage` (tokens/cost). Additive migration `08_create_ai_tables.sql`, same hand-run convention. No existing table is altered. | — |
| `jobs/*` | One interface (`submit(run) → run_id`), two implementations: inline await and `BackgroundTasks`. A future queue/worker drops in behind the same interface — no caller changes. | — |
| `api/*` | Thin routes: create run (agent key + input), poll run, stream run (SSE), list capabilities for the caller's role. Delegates entirely to `runtime/`. Uses the existing `get_current_user`/role deps. | — |
| `facade.py` | The strangler seam: plain async functions like `generate_exam(context, request) → ExamResponse` that existing routes call without knowing about agents, runs, or the SDK. | — |

---

## 4. Dependency Boundaries

```
                    ┌────────────────────────────────────────────┐
   app/main.py ────▶│  ai/api/routes.py          (mounted /api/ai)│
   app/api/routes/  │  ai/facade.py              (strangler seam) │   ← the ONLY two inbound doors
        teacher.py ─▶└────────────────┬───────────────────────────┘
                                      ▼
                     ai/runtime  ← ai/agents ← ai/instructions
                          │            │
                          │            ▼
                          │        ai/tools  ──▶ ai/policies, ai/guardrails, ai/schemas
                          ▼            │
                    ai/persistence     ▼
                          │      app/services/*   (existing, unchanged)
                          ▼            │
                    app/models (Base)  ▼
                                 app/models, app/database (existing, unchanged)
```

Hard rules (enforceable by import-linter/review):

1. `app/services`, `app/models`, `app/schemas`, `app/api` **must not** import `app.ai.*`.
2. `ai/agents` **must not** import `app.services`, `app.models`, or `ai.persistence` — tools only.
3. `ai/tools` **must not** import the SDK's model classes or `runtime/provider` — no tool ever calls a model.
4. Only `runtime/provider.py` constructs an LLM client. `services/openai_service.py` remains as-is during migration and is retired at the end (Phase 4), not modified.
5. `ai/persistence` shares the SQLAlchemy `Base` and session factory from `app/database` but defines only new `ai_*` tables; it never maps or migrates existing tables.
6. DB sessions are created per tool invocation (or per run, held by the context factory) — never global, never shared across threads.

---

## 5. Extension Points

Each maps to a seam identified in `REPORT.md` §18. Adding a capability = add a tool (and, if needed, a service method) + an agent or an agent's tool-list entry + a registry row. No runtime/plumbing changes.

| Extension point | Layer additions | Existing seam it lands on |
|---|---|---|
| **Exam generation** (first migration target) | `exam_generator` agent + `materials`/`exams` tools; output guardrail validates counts/types | The `/exams/generate` route, `ParserService`, `ExamService.create_exam` |
| **Text-answer grading assist** | `grader` agent + `results` tool writing via a *new service method*; teacher confirms — agent proposes, service persists | `exam_results.reviewed_at/reviewed_by/feedback` columns (never written today), tri-state `exam_responses.is_correct` |
| **Question bank** | `question_bank` tools over new service methods; generator agent gains save/reuse tools | `question_bank` table + GIN-indexed `tags` (currently an island) |
| **Analytics / item analysis** | `analytics` agent, read-only `results` tools | `exam_responses` per-question correctness, difficulty labels; admin dashboard's empty panels |
| **Student guidance** | `student_assistant` agent (sessions enabled), own-data-only tool scope | Student dashboard/results surfaces; `notifications` table as delivery channel |
| **Teacher assistance** | `teacher_assistant` agent; handoff target from `triage` | Manual exam builder, materials |
| **Notifications delivery** | `notifications` tool over a new service | `notifications` table + model (unused today) |
| **Audit/observability** | tracing processor writing run summaries | `audit_logs` table (unused today) |
| **New model/provider** | one branch in `runtime/provider.py` (or a `ModelProvider` impl) | existing prefix-routing convention |
| **Queue-based execution** | new `jobs/` adapter behind the same interface | — |

---

## 6. Integration Strategy (Strangler, Feature-Flagged)

**Phase 0 — Foundation (no behavior change).**
Add `openai-agents` to `pyproject.toml` (+ sync `requirements.txt` — note the audit's existing drift). Create the package skeleton, `AISettings` (`AI_ENABLED`, `AI_USE_AGENTS_FOR_GENERATION`, quota knobs — all defaulting to off), `provider.py` reproducing the current base-url convention, `persistence` models + migration `08`, and mount `/api/ai` returning capabilities only. Existing endpoints untouched.

**Phase 1 — Migrate exam generation (the strangler proof).**
`POST /api/teachers/exams/generate` branches on the feature flag: **on** → `ai.facade.generate_exam(...)` (triage-less direct run of `exam_generator`: input guardrail validates `question_config`; `materials` tool extracts text off-thread; structured output validated by output guardrail; `exams` tool persists via `ExamService.create_exam`); **off** → the current `OpenAIService` path, byte-for-byte. Same request/response schemas, same route, same auth. This single migration fixes four audit findings in-place: unvalidated config, unverified LLM output, event-loop blocking, and provider-error leakage.

**Phase 2 — New AI surface.**
Enable `POST /api/ai/runs` + polling/streaming for the assistant-style agents (`grader`, `analytics`, `teacher_assistant`, `student_assistant`) with sessions, quotas, and background execution for long runs. Frontend consumes it through the existing `lib/api.ts` pattern (new `aiApi` group). The current simulated progress stepper gains a real progress source (run status / SSE).

**Phase 3 — Handoffs and triage.**
Introduce `triage` as the single front-door agent using SDK handoffs to specialists, so the client asks for *outcomes* rather than naming agents. Registry capability listing drives what each role's UI offers.

**Phase 4 — Retire the legacy path.**
When the flag has been on and stable: delete `services/openai_service.py`, remove the flag, keep `ParserService` (it is a service-layer utility the tools wrap, not AI plumbing).

**Rollback at every phase** = flip the flag off; the legacy path is never modified while it is still reachable.

---

## 7. Cross-Cutting Decisions

- **Identity & RBAC:** `/api/ai` routes use the existing `api/deps.py` guards; `AIRunContext` carries the resolved `User`. Tools re-check via `policies/authz.py`. The model never sees credentials, tokens, or another user's row-scope.
- **Error contract:** all AI-surface errors flow through `runtime/errors.py` into the existing custom exceptions, producing the standard `{"error": {code, message, details}}` envelope. New codes: `AI_DISABLED`, `AI_QUOTA_EXCEEDED`, `AI_GUARDRAIL_REJECTED`, `AI_RUN_FAILED`, `AI_RUN_TIMEOUT`.
- **Budgets/timeouts by default:** every run gets `max_turns`, a wall-clock timeout, and `max_tokens` from `AISettings` — none of which the current AI call has.
- **Determinism for tests:** `provider.py` accepts an injected fake model client; agents are testable with stub tools; tools are testable with a test DB and no model. (This layer is the first part of the backend designed test-first — the audit records zero existing tests.)
- **Config additivity:** new `AI_*` env vars only; existing `OPENAI_API_KEY`/`OPENAI_MODEL` remain the defaults they feed. Nothing existing is renamed.
- **Non-goals (explicit):** no fine-tuning/embeddings/RAG store in v1 (a `retrieval` tool module is a future extension point); no autonomous writes — every mutating tool call happens within a user-initiated, role-authorized run; no modification of existing tables, routes, services, or the frontend guard model.

---

*End of design. Implementation order, module stubs, and migration `08` DDL follow this document; prompts/instructions and business logic are intentionally out of scope.*
