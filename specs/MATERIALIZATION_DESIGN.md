# Assessment Materialization — Design & Implementation Map

> Companion to `ASSESSMENT_WORKFLOW_DESIGN.md`. Implemented in
> `backend/app/ai/workflows/assessment/materialization.py`.
> Scope: the last three steps of `Assessment_Intelligence.md` — **AI generates
> questions → quality is validated → the teacher publishes** — closing the
> gap between an approved `AssessmentPlan` and an exam students can sit.

## 1. Why this is not a sixth stage

`ASSESSMENT_WORKFLOW_DESIGN.md` §6 already settled the shape: *"The eventual
question-generation phase is a **new pipeline consumer**, not a new stage: it
reads a `completed` workflow's `AssessmentPlan` and drives the existing
`exam_generator` → `ExamService.create_exam` path."* This phase implements
exactly that.

Concretely, a stage would have been wrong on three counts:

- Stages produce **artifacts** (JSON on `ai_workflow_stages`). Materialization
  produces **rows in the platform's own `exams`/`questions` tables** — a
  different kind of effect, governed by different rules.
- `COMPLETED` is a **terminal** workflow state with no outgoing transitions.
  Adding post-completion stages would mean reopening a terminal state and
  invalidating the guard tables every existing test asserts on.
- Stages re-run on rejection. An exam that has been generated (and possibly
  published) must not be silently re-run; it has its own lifecycle.

So the planning pipeline is unchanged and still ends at `COMPLETED`. The
generation lifecycle lives beside it, in its own table with its own guards.

```
 planning pipeline (unchanged)                materialization (this phase)
 ─────────────────────────────                ────────────────────────────
 draft → in_progress ⇄ awaiting_approval      pending → generating → generated
                    → COMPLETED  ────────────▶                          │
                       (AssessmentPlan)          │                      ▼
                                                 └→ failed         PUBLISHED
                                                                  (human only)
```

## 2. The three properties, in priority order

**1. Publishing is a human action.** This is the phase's hard constraint and
it inherits directly from the Scheduler's (`SCHEDULER_DESIGN.md`). It is
enforced five ways, not one:

| Enforcement | Where |
|---|---|
| `PUBLISHED` reachable only from `GENERATED` | `GENERATION_TRANSITIONS` in `domain.py` |
| `PUBLISHED` is terminal (no silent regeneration over a live exam) | same table |
| Only `_publish_sync` may reference `ExamService.publish_exam` | module-wide AST test |
| The generation path references no publish identifier at all | AST test over `build_generation_input`, `to_exam_create`, `generate_assessment` |
| No agent has a publishing tool; no role has a publishing capability | `authz.py` + `exam_generator.DEFINITION` |

Generation *always* yields an unpublished draft — `ExamCreate` has no
`is_published` field, so it cannot express anything else.

**2. The model never writes rows.** The agent returns `GeneratedExamOutput`;
the validated result is projected onto `ExamCreate` by `to_exam_create()` and
persisted through `ExamService`, exactly as `facade.py` does for the legacy
path. No duplicated business logic, no writes outside the service.

**3. Generation follows what was *approved*, not what was requested.** The
count skeleton comes from `AssessmentPlan.blueprint` via
`blueprint_question_config()`. This matters because a rejection with a
`config_patch` legitimately moves the blueprint away from the original
creation request — the teacher approved the blueprint, so the blueprint wins.

## 3. Flow

```
POST .../{id}/generate
  ├─ gate: workflow COMPLETED, plan present
  ├─ gate: plan_blockers() empty   (quality passed, no standing blockers,
  │        readiness ≠ blocked, blueprint non-empty and error-free)
  ├─ gate: resolve_duration()      (fails BEFORE spending a model call)
  ├─ claim attempt row → GENERATING   (unique (workflow_id, attempt)
  │                                     serializes double-submits)
  ├─ extract text from the approved, parseable materials
  ├─ execute_run("exam_generator", blueprint + allocations + material text)
  │     guardrails: counts / mixes / option integrity are tripwires
  ├─ validate_generated_against_blueprint()  → findings (not fatal)
  ├─ ExamService.create_exam(...)            → UNPUBLISHED draft
  └─ row → GENERATED (exam_id, run_id, question_count, findings)

POST .../{id}/publish   {acknowledge_findings}
  ├─ requires GENERATED, an existing exam, question_count > 0
  ├─ requires acknowledge_findings=true IF findings are non-empty
  └─ ExamService.publish_exam(exam_id, True) → row PUBLISHED
```

## 4. Two-tier quality validation

The spec's "AI validates quality" applies at two different moments, and they
answer different questions:

| | `quality_review` stage | this phase |
|---|---|---|
| Subject | the **plan** (blueprint vs outline) | the **generated questions** |
| When | before the teacher approves | after generation, before publishing |
| Failure mode | blocks workflow completion | recorded as findings |

Post-generation checks are layered: counts, mixes, and option integrity are
already **tripwires** on the agent's output guardrail (shared with the legacy
path), so what survives to `validate_generated_against_blueprint()` is the
blueprint-level deviation — *did each topic get the number of questions it
was allocated?* Those become `findings` the teacher must explicitly
acknowledge at publish time rather than a hard failure, because a slightly
skewed topic distribution is a judgment call, not a corruption.

Topic verification needs a signal the exam schema doesn't carry, so
`GeneratedQuestion` gained an optional `topic` field. It is a
**generation-time verification signal only** and is deliberately not
persisted (there is no topic column on `questions`). When the design has no
allocations, or the model tagged nothing, topic checks are **skipped rather
than passed** — the same honesty rule as the quality reviewer's
`not_assessable`.

## 5. Persistence

`ai_workflow_generations` (migration `12` = Alembic `0006`) — one row per
**attempt**, so the audit trail the spec asks for is complete: which run
produced the questions, what validation said, which exam it became, and when
a human published it.

- `exam_id` is `ON DELETE SET NULL`: deleting a draft exam must not erase the
  record that it was generated.
- Regenerating marks the previous attempt `superseded` and **leaves its draft
  exam in place** — deleting a teacher's exam is never implicit. The orphan
  draft is removable through the existing exam endpoints.
- A published assessment cannot be regenerated over; unpublish first.

## 5a. Execution model

`generate_assessment()` claims the attempt row **synchronously** — so the
caller immediately observes `generating`, and the unique `(workflow_id,
attempt)` constraint rejects a concurrent second request — then runs
`_materialize()` detached via `ai/jobs/tasks.spawn()`. This is the longest
call in the product; holding a request open for it is what made progress
unreportable.

Because execution is in-process, a worker restart would leave the row
`generating` forever. `_reclaim_stale()` fails any attempt older than
`2 × run_timeout + 60s` on read — lazy, since the only moment it matters is
when somebody looks.

`background=False` awaits completion, for scripts and tests.

## 6. Configuration

`AI_USE_MATERIALIZATION` (default **true**, unlike the stage flags). It does
not change how an existing stage behaves — it completes the teacher's journey
— and it is already gated by the `AI_ENABLED` master switch, since it needs a
model run. Set it false to keep the pipeline planning-only.

## 7. Boundaries (unchanged from the AI layer's rules)

- Reads and writes to existing tables go **only** through `ExamService` /
  `MaterialService`; the workflow still owns only its `ai_workflow*` tables.
- No DB session is held across an await; every DB step is a sync function run
  via `asyncio.to_thread`.
- Nothing outside `app/ai` imports this module; it is reached only through the
  mounted router.
