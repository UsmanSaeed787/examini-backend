# Assessment Intelligence Workflow — Design & Implementation Map

> Companion to `AI_LAYER_DESIGN.md`. Implemented in `backend/app/ai/workflows/assessment/`.
> Scope: workflow orchestration, domain models, schemas, tool interfaces, state
> transitions, and human approval checkpoints. The pipeline ends with an
> approved `AssessmentPlan`; **question generation is out of scope here** and
> is implemented as a downstream consumer — see `MATERIALIZATION_DESIGN.md`.

## 1. Concept

An **assessment workflow** is a stateful, teacher-owned pipeline instance:
select a class + materials + question config → stages execute in order →
each stage produces a **typed artifact** → the teacher approves or rejects at
**checkpoints** → the final approval assembles an `AssessmentPlan` stored on
the workflow. Every stage is a **pluggable handler**; v1 handlers are
deterministic (reads through existing services + pure computation, no LLM),
and each one is the seam a future specialist agent replaces.

| Stage | Future specialist | v1 deterministic behavior | Artifact |
|---|---|---|---|
| `curriculum_analysis` | Curriculum Analyst | Class + material inventory via `ClassService`/`MaterialService`; parseability flags | `CurriculumOutline` |
| `assessment_design` | Assessment Designer | Normalizes `question_config` into a blueprint (guardrail-validated) | `AssessmentBlueprint` |
| `quality_review` | Quality Reviewer | Deterministic consistency checks over upstream artifacts | `QualityReport` |
| `difficulty_analysis` | Difficulty Analyzer | Target mix vs the teacher's historical exams (`ExamService`) | `DifficultyProfile` |
| `scheduling` | Scheduler | Window/duration validation from teacher constraints | `SchedulePlan` |

## 2. State machines (enforced in `state_machine.py`; every mutation guarded)

```
Workflow: draft → in_progress ⇄ awaiting_approval → completed
                     │                    │
                     ├→ failed            └→ cancelled   (cancel from any non-terminal)

Stage:    pending → running → in_review → approved
                       │          └→ rejected → pending (revision+1, re-runs)
                       └→ failed → pending (retry seam)
```

**Approval modes** (chosen at creation): `every_stage` (default), `final_only`,
`none` (fully automatic). `checkpoint_required(mode, stage, pipeline)` is the
single policy function.

**Auto-advance:** after a stage completes, the orchestrator either stops at
the checkpoint or auto-approves and immediately runs the next stage.
`approve`/`reject` resume the same loop. Rejection records the decision,
bumps the stage `revision`, optionally merges a `config_patch` into the
workflow config, and re-runs the stage with the reviewer's notes in context.

## 3. Module map (`backend/app/ai/workflows/assessment/`)

| File | Responsibility |
|---|---|
| `domain.py` | `StageKey`, `WorkflowState`, `StageStatus`, `ApprovalMode`, `CheckpointDecision`, `DEFAULT_PIPELINE` |
| `state_machine.py` | Pure transition tables + guards + checkpoint policy (fully unit-tested) |
| `schemas.py` | Stage artifact contracts (`ARTIFACT_TYPES` map — the agent plug-in contract) + API DTOs |
| `stages.py` | `StageHandler` ABC, `StageContext`, registry, 5 deterministic handlers, **`AgentStageHandler`** adapter |
| `service.py` | The only state mutator: create/start/approve/reject/cancel; async surface, sync DB steps via `to_thread` |
| `persistence.py` | `ai_workflows`, `ai_workflow_stages` (unique per workflow+stage, keeps artifact + revision), `ai_workflow_checkpoints` |
| `api.py` | Teacher-only router mounted at `/api/ai/workflows/assessment` |

Supporting pieces elsewhere: `ai/tools/workflow.py` (read tools
`get_assessment_workflow` / `get_stage_artifact`, capability `workflow.read`
in the authz matrix — the tool interface future specialists and the teacher
assistant use to see upstream artifacts); migration
`09_create_assessment_workflow_tables.sql` = Alembic `0003_assessment_workflows`.

## 4. API surface

```
POST   /api/ai/workflows/assessment                      create (DRAFT)
POST   /api/ai/workflows/assessment/{id}/start           run to first checkpoint
GET    /api/ai/workflows/assessment                      list mine
GET    /api/ai/workflows/assessment/{id}                 full state + artifacts
POST   .../{id}/stages/{stage}/approve   {notes?}        approve → auto-advance
POST   .../{id}/stages/{stage}/reject    {notes, config_patch?}  re-run stage (new revision)
POST   /api/ai/workflows/assessment/{id}/cancel
```

All behind the existing bearer auth + `AI_ENABLED`; teacher role required;
rows scoped by `user_id`; errors use the standard envelope.

## 5. Integration boundaries (unchanged from the AI layer's rules)

- Handlers read **only through existing services** (`ClassService`,
  `MaterialService`, `ExamService`) — no duplicated business logic, no writes
  to existing tables. The workflow owns only its three `ai_workflow*` tables.
- Handlers hold no DB session across awaits; sync work runs off the event loop.
- Nothing outside `app/ai` imports the workflow; it is reached only via the
  mounted router.

## 6. How a future specialist plugs in

1. Add the agent to `ai/agents/` + registry (structured output =
   `ARTIFACT_TYPES[stage]`, tools typically `workflow.get_stage_artifact` +
   domain read tools).
2. Replace one line in `stages.py`:
   `register(AgentStageHandler(StageKey.X, agent_key="curriculum_analyst"))`.
3. Nothing else changes — orchestrator, schemas, API, checkpoints, quotas,
   and run accounting (the agent run goes through `runtime/runner.py` and is
   recorded on the stage's `run_id`) all apply automatically.

The question-generation phase is a **new pipeline consumer**, not a new
stage: it reads a `completed` workflow's `AssessmentPlan` and drives the
existing `exam_generator` → `ExamService.create_exam` path. Implemented in
`materialization.py` — see `MATERIALIZATION_DESIGN.md`. `COMPLETED` therefore
remains terminal, and this document's state machines are unchanged by it.
