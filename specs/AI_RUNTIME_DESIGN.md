# AI Runtime — Kernel of the Educational Agent OS

> Companion to `AI_LAYER_DESIGN.md` (foundation) and
> `ASSESSMENT_WORKFLOW_DESIGN.md` (first capability). Implemented in
> `backend/app/ai/runtime/`. The runtime is **generic**: it contains no
> agents, no prompts, no business logic, and no workflow-specific code. It
> executes and orchestrates whatever plugs into its interfaces — Assessment
> Intelligence today; Student Success Intelligence, Teacher Copilot,
> Administrator Intelligence, Academic Analytics, and Career Intelligence
> tomorrow.

## 1. Architecture

Three layers inside `runtime/`, dependencies pointing strictly downward:

```
┌─────────────────────────────────────────────────────────────────┐
│ ORCHESTRATION      runner.py (agent runs)   execution.PipelineExecutor │
│                    — compose primitives into full executions —   │
├─────────────────────────────────────────────────────────────────┤
│ INFRASTRUCTURE     lifecycle  events  metrics  tracing  quotas   │
│                    registry   sessions  provider                 │
├─────────────────────────────────────────────────────────────────┤
│ PRIMITIVES         interfaces  context  results  exceptions      │
│                    (protocols, dataclasses, error codes — no I/O)│
└─────────────────────────────────────────────────────────────────┘
```

Capabilities live **outside** the kernel and connect only through
`interfaces.py` protocols (dependency inversion): the kernel never imports
capability code; capabilities implement `PipelineHooks`, register
`WorkflowDefinition`s, subscribe `EventSink`s, or swap `QuotaPolicy` /
`CostTracker` / `MetricsSink` implementations.

## 2. Module responsibilities

| Module | Responsibility |
|---|---|
| `interfaces.py` | All kernel contracts: `EventSink`, `MetricsSink`, `QuotaPolicy`, `CostTracker`, `ExecutableStage`, `PipelineHooks`, `StagePlan`, `AttemptFactory` |
| `context.py` | `ExecutionContext` — correlation (trace_id, run/workflow/stage ids), attempt number, cancellation token. Carries (never replaces) the identity `AIRunContext` |
| `exceptions.py` | Canonical error surface: re-exports the HTTP-mapped `AIError` family + `ExecutionCancelledError` (409), `RetryExhaustedError`, `RegistryError`. One handler covers everything |
| `results.py` | Structured outcomes: `ExecutionResult[T]` (status/output/error/usage/timing/attempts) and `PipelineResult` (completed/paused/failed/idle) |
| `lifecycle.py` | `run_with_lifecycle(factory, timeout, retry, token)` — timeout + retry (`RetryPolicy`, total-attempt semantics, typed retry_on) + cooperative cancellation (`CancellationToken`, process-wide `run_registry`). Pure asyncio, SDK-free |
| `events.py` | Async `EventBus` + `RuntimeEvent` + `EventTypes` (run/stage/pipeline/cost). Default logging sink; failing sinks never break execution |
| `metrics.py` | `InMemoryMetricsSink` (counters + bounded observations + snapshot) behind the `MetricsSink` protocol |
| `tracing.py` | `span()` — the shared instrumentation primitive (events + duration metrics around any unit) + SDK usage extraction (`extract_usage`) and output summarization |
| `registry.py` | Generic `Registry[T]` (duplicate-safe, typed) + `WorkflowDefinition` + the `workflow_registry` capability catalog that feeds `/api/ai/capabilities` |
| `quotas.py` | `DailyUserQuotaPolicy` (delegates numbers to `policies/quotas.py`), `EventCostTracker` (publishes `cost.recorded` — the pricing hook), null variants for tests |
| `execution.py` | The two engines: `execute_agent()` (single-attempt SDK run; the only SDK-touching module besides `provider.py`, lazy-imported) and `PipelineExecutor` (generic pause-aware stage loop over `PipelineHooks`) + `transient_exceptions()` retry classifier |
| `runner.py` | Agent-run orchestration composing everything: registry → quota → run record → lifecycle(execute_agent) → usage → cost tracker → events/metrics → `RunOutcome`. Public API unchanged (`execute_run`, `ensure_enabled`) + additive `cancel_run` |
| `provider.py` / `sessions.py` / `errors.py` | Unchanged from the foundation: model client factory (OpenAI/Gemini routing), DB-backed SDK sessions, HTTP error envelope |

## 3. Sequence diagrams

**Agent run** (API `/runs`, facade, or an agent-backed workflow stage):

```
caller ──execute_run(identity, agent_key, input)──▶ runner
  runner ─▶ agents.registry: role-gate agent_key
  runner ─▶ QuotaPolicy.check(identity)              ── 429 on exhaustion
  runner ─▶ store.create_run / mark_running          ── ai_runs row
  runner ─▶ event_bus: run.started
  runner ─▶ run_with_lifecycle(                      ── lifecycle.py
              factory = execute_agent(...)           ── SDK Runner.run, one attempt
              timeout = AI_RUN_TIMEOUT_SECONDS
              retry   = transient only (AI_MAX_RETRIES)
              token   = run_registry[run_id])        ── cancellable via /runs/{id}/cancel
  ├─ success ─▶ extract_usage ─▶ store.complete_run ─▶ CostTracker.record
  │            ─▶ event_bus: run.completed ─▶ RunOutcome
  └─ failure ─▶ map_sdk_exception ─▶ store.fail_run
               ─▶ event_bus: run.failed | run.cancelled ─▶ raise AIError
```

**Pipeline with human approval pause/resume** (any capability):

```
capability.start ──▶ PipelineExecutor.run(hooks)
  loop:
    hooks.begin_stage() ──▶ StagePlan | None ── None → COMPLETED (or IDLE)
    span("stage"): plan.handler.execute(plan.context) → artifact
                   plan.validate(artifact)
    ├─ raises (caught types) ─▶ hooks.fail_stage ─▶ FAILED
    hooks.complete_stage(plan, artifact, paused=plan.pause_after)
    plan.pause_after? ──▶ event: pipeline.paused ─▶ PAUSED   ← human checkpoint
                          … human approves via capability API …
capability.approve ──▶ (hooks persist decision) ──▶ PipelineExecutor.run(hooks)  ← resume
```

The kernel owns the loop, instrumentation, and pause semantics; the
capability's hooks own persistence, transitions, and checkpoint policy —
which is exactly how Assessment Intelligence now runs (`_AssessmentHooks`
in `workflows/assessment/service.py`).

## 4. Responsibilities checklist (from the brief)

| Requirement | Where |
|---|---|
| Workflow / stage execution | `execution.PipelineExecutor` + `PipelineHooks` |
| Agent execution lifecycle | `runner.execute_run` + `execution.execute_agent` |
| Tool execution | `tools/_base.call` (authz + off-thread), unchanged, kernel-compatible |
| Context propagation | `context.ExecutionContext` (trace + identity + cancellation, `derive()`) |
| Cancellation | `lifecycle.CancellationToken` / `run_registry` + `POST /api/ai/runs/{id}/cancel` |
| Retry / timeout | `lifecycle.RetryPolicy` + `run_with_lifecycle` (`AI_MAX_RETRIES`, `AI_RETRY_BACKOFF_SECONDS`, `AI_RUN_TIMEOUT_SECONDS`) |
| Structured results | `results.ExecutionResult` / `PipelineResult` (+ legacy `RunOutcome` preserved) |
| Tracing / logging | `tracing.span` + `events.LoggingEventSink` |
| Metrics | `metrics.InMemoryMetricsSink` (protocol-swappable) |
| Run history | `persistence/store.py` (`ai_runs`/`ai_usage`), unchanged |
| Cost tracking hooks | `quotas.EventCostTracker` + `cost.recorded` events |
| Event publishing | `events.EventBus` (pluggable sinks) |
| Human approval pause/resume | `StagePlan.pause_after` → `PipelineStatus.PAUSED` → capability approve/reject re-enters the executor |

## 5. Integration strategy (done + future)

**Done in this pass (no public API broken):**
- `runner.execute_run` re-built on the kernel — same signature; facade,
  background jobs, and `AgentStageHandler` untouched.
- Assessment's `_run_pipeline` deleted its hand-rolled loop and now runs on
  `PipelineExecutor` via `_AssessmentHooks` (~40 lines of hooks).
- Assessment registered in `workflow_registry`; `/api/ai/capabilities` now
  lists workflows alongside agents; `/api/ai/runs/{id}/cancel` added.

**A future capability (e.g. Student Success Intelligence) integrates by:**
1. Defining its stages as `ExecutableStage` handlers (deterministic or
   `AgentStageHandler`-style) and its artifacts as Pydantic models.
2. Implementing `PipelineHooks` over its own persistence.
3. Calling `PipelineExecutor.run(hooks)` from its service; pause/resume and
   instrumentation come free.
4. Registering a `WorkflowDefinition` for capability discovery.
5. (Optional) subscribing sinks for its own eventing/metrics needs.

**Limits (stated, not hidden):** cancellation and the event bus are
in-process (a multi-worker deployment needs a shared bus/queue behind the
same protocols); metrics are in-memory until a Prometheus sink replaces the
default; cost tracking records usage — monetary pricing is a subscriber to
`cost.recorded`, not yet implemented.
