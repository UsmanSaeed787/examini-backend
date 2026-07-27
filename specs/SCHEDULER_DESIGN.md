# Scheduler Agent — Phase 10 of the Educational Agent OS

> The **fifth business agent**, completing the Assessment Intelligence
> pipeline: every stage now has a specialist. Implemented in
> `backend/app/ai/agents/scheduler.py` plus the deterministic scheduling core
> and both handlers in the workflow's `stages.py`.

## 1. What it analyzes

| Input | Source |
|---|---|
| **Teacher constraints** | the workflow config: proposed window and duration |
| **Duration** | estimated from the blueprint's question mix (below) |
| **Academic calendar** | other exams for the same class whose window overlaps (see §3) |

and returns a readiness verdict — `ready` / `adjust` / `blocked` /
`insufficient_information` — with reasoning, recommendations, and an
optional *suggested* duration.

## 2. Duration estimation (deterministic)

Per-question time rates make the estimate explainable rather than a guess:

| Type | Minutes |
|---|---|
| `mcq` | 1.5 |
| `true_false` | 1.0 |
| `short_answer` | 4.0 |
| `long_answer` | 10.0 |
| (no type mix) | 2.0 × total questions |

The rates used are recorded on the artifact as `duration_basis`, so a
teacher can see *why* a number was suggested. A requested duration below
75 % of the estimate raises a warning ("60 min may be tight — this question
mix suggests about 95 min"); when no duration is set at all, the estimate is
offered as an `info` finding.

## 3. "Academic calendar" — what actually exists

**Examini has no institutional academic calendar**: there are no term,
holiday, or timetable tables in the schema. Rather than invent one, the
calendar analysis uses the real signal the platform has — **other exams
scheduled for the same class whose window overlaps the proposed one**, with
the overlap in minutes. Each collision becomes a warning finding, and the
agent is told explicitly in its instructions that it knows nothing about
terms or holidays, so it cannot fabricate calendar constraints.

`load_schedule_conflicts()` is the seam: a real calendar can be added behind
that one function without touching the agent, the artifact, or the handlers.

## 4. Timezone safety

The audit flagged naive/aware datetime mixing elsewhere in the platform, so
all window arithmetic goes through `_as_aware_utc()`: ISO strings are
parsed, naive values are treated as UTC, aware values are normalized.
Unparseable input becomes `None` instead of raising. Tested with a mixed
naive/aware window.

## 5. No publishing — enforced three ways

1. The agent has **zero tools**, so it cannot reach `ExamService.publish_exam`
   or any other mutation.
2. `SchedulePlanOutput` has no `publish`/`is_published`/`approved` field.
3. An **AST-based test** walks the identifiers referenced by every function
   in the scheduling path (`plan_schedule`, both handlers' `execute`,
   `_run_agent`, `merge_schedule_plan`) and fails if any name contains
   "publish" — prose in docstrings doesn't count, only real code.

Additionally, `merge_schedule_plan()` never applies the agent's suggested
duration: `duration_minutes` stays the teacher's value and the suggestion is
recorded separately as `recommended_duration_minutes` (tested). Publishing
remains a deliberate human action in the existing teacher API.

## 6. Guardrail

Same honesty rules as the other analysts: a readiness verdict cannot be
claimed with no proposed window (must be `insufficient_information`), that
verdict cannot be used when a window *does* exist, and `adjust`/`blocked`
must come with at least one recommendation. `ready` needs none.

## 7. Enabling it

```bash
AI_ENABLED=true
AI_USE_SCHEDULER=true
```

Flag off (default) keeps the deterministic handler — which is itself now a
much stronger analysis than before (duration estimation, window length,
calendar conflicts), and works with the AI layer switched off entirely.
