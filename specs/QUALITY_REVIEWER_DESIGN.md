# Quality Reviewer Agent — Phase 8 of the Educational Agent OS

> The **third business agent**, and the first that can *block* a workflow.
> Implemented in `backend/app/ai/agents/quality_reviewer.py` plus the
> assessment workflow's `QualityReviewerHandler`. It consumes the
> `AssessmentBlueprint` and returns the `QualityReport` — with **no workflow
> orchestration**.

## 1. What it does

Given the blueprint, the curriculum outline behind it, and the institution's
academic policies, it issues one verdict per required dimension plus
attributed observations:

| Dimension | Question it answers |
|---|---|
| `coverage` | Do allocations span the curriculum in proportion to topic emphasis? |
| `difficulty_balance` | Is the easy/medium/hard mix sensible and as requested? |
| `question_distribution` | Are question types appropriate and reasonably spread? |
| `bloom_taxonomy` | Do targeted cognitive levels match the learning outcomes? |
| `institution_policies` | Does the blueprint respect caps, pass threshold, grading bands? |

Each verdict is `pass` / `concerns` / `fail` / `not_assessable` — the last
being an honest answer when the artifacts carry no data for that dimension
(e.g. coverage with no topic allocations), so the agent never fabricates an
assessment it cannot support.

## 2. The safety property: blockers are add-only

This is the phase's most important design decision. The `passed` flag gates
the whole assessment pipeline, so it is **never model-authored**:

```python
passed = deterministic.passed and not any(agent blocker)
```

The agent can *introduce* a blocker (failing a blueprint the structural
checks let through — exactly what a reviewer is for), but it can **never
clear one**. An all-pass review cannot rescue a report the platform's own
checks failed. Both directions are covered by tests.

## 3. No workflow orchestration

- The output models contain no `passed`, `approved`, `next_stage`,
  `stage_status`, or `decision` field (asserted by test); the agent has no
  vocabulary for pipeline control.
- It has **zero tools**, so no database reach, direct or indirect.
- Stage transitions, checkpoints, and the approve/reject decision stay with
  the orchestrator and the human reviewer.

## 4. Hybrid stage

- **Deterministic half** — `review_quality(outline, blueprint)` runs first:
  it propagates the outline's findings, turns blueprint `validation_errors`
  into blockers, checks material parseability and coverage thinness, and
  computes the authoritative `passed`.
- **Agent half** — `dimension_verdicts`, `observations`, `summary`, merged by
  `merge_quality_report()` (add-only, above). Observations become findings
  prefixed with their dimension, e.g. `[coverage] Half the syllabus is untested`.

**Fallback**: when the deterministic pass already found blockers, the agent
is skipped — the teacher must fix those first, so a nuanced review would
just cost tokens. Missing upstream artifacts fail the stage cleanly with a
`ValidationError` rather than a raw `KeyError`.

**Institution policies** come from the Context Engine's
`AcademicPolicyProvider` (pass threshold and grade bands *derived from the
platform's own `calculate_grade()`*, plus the question cap) and are passed
into the run input — no policy values are re-declared for the agent.

## 5. Guardrail

`validate_quality_review()` enforces that the review is complete and
substantiated: every one of the five dimensions is covered **exactly once**,
and any `concerns`/`fail` verdict has at least one supporting observation on
that dimension. No silently skipped checks, no unexplained failures.

## 6. Enabling it

```bash
AI_ENABLED=true
AI_USE_CURRICULUM_ANALYST=true     # supplies topics -> coverage/Bloom become assessable
AI_USE_ASSESSMENT_DESIGNER=true    # supplies allocations
AI_USE_QUALITY_REVIEWER=true       # quality_review stage → the agent
```

Flag off (default) keeps the deterministic handler byte-for-byte; the switch
happens in `configure_quality_stage()` at registration. The reviewer works
standalone but is most informative with the upstream agents on — without
topics or allocations it will honestly mark coverage and Bloom
`not_assessable`.
