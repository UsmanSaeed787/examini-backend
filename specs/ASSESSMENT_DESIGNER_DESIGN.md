# Assessment Designer Agent — Phase 7 of the Educational Agent OS

> The **second business agent**, and the first that consumes another agent's
> artifact. Implemented in `backend/app/ai/agents/assessment_designer.py`
> plus the assessment workflow's `AssessmentDesignerHandler`. It consumes the
> `CurriculumOutline` and produces the `AssessmentBlueprint`, using the AI
> Runtime — with **no database access, no workflow logic, and no
> scheduling**.

## 1. What it does

Given the curriculum's topics (learning outcomes, Bloom levels, emphasis)
and the teacher's requested question counts, it decides **how the exam
distributes across the curriculum**: how many questions each topic gets, of
which types, targeting which cognitive levels, and why.

```
CurriculumOutline (Phase 6)  ─┐
teacher's question_config    ─┴─▶ Assessment Designer ─▶ AssessmentBlueprint.topic_allocations
                                                          + rationale
```

## 2. How the phase's three prohibitions are enforced

| Constraint | Enforcement |
|---|---|
| **No database access** | The agent has **zero tools** (`required_tools = ()`, `tools=[]` — asserted by test). Everything it reasons over is placed in the run input by the stage handler, which reads artifacts deterministically. There is no direct or indirect data reach. |
| **No workflow logic** | It returns an artifact and nothing else. Stage transitions, checkpoints, approvals, and revisions remain entirely in the orchestrator/hooks; the agent has no vocabulary for them. |
| **No scheduling** | `AssessmentDesignOutput` and `TopicAllocation` contain no duration/date fields (asserted by test), and the instructions explicitly forbid scheduling. Duration and windows stay in `SchedulePlan` (the Scheduler stage). |

## 3. Hybrid stage: deterministic skeleton + agent design

`AssessmentBlueprint` splits the same way `CurriculumOutline` does:

- **Count skeleton** (total, `type_mix`, `difficulty_mix`, points,
  `estimated_total_points`) — always derived deterministically from the
  teacher's `question_config` via `normalize_blueprint()`. The model cannot
  change what the teacher asked for.
- **Design** (`topic_allocations`, `rationale`) — the agent's contribution,
  merged by `merge_blueprint()` with `model_copy(update=...)`.

Both fields are additive, so the deterministic v1 handler and the agent
handler satisfy one artifact contract (verified by test), and downstream
stages (`quality_review`, `difficulty_analysis`) keep working unchanged.

**Fallbacks** (skeleton returned, no tokens spent): invalid or empty
`question_config`; the curriculum stage produced no topics (i.e. the
deterministic curriculum handler ran); or the curriculum artifact is
missing. An agent failure fails the stage visibly rather than degrading.

## 4. Validation, split by concern

- **Guardrail (tripwire → `AI_GUARDRAIL_REJECTED`)** —
  `validate_assessment_design()`: allocations must be non-empty, must
  reference **only topics from the outline** (no invented topics), must not
  duplicate a topic, must use known question types whose per-topic counts
  sum to that topic's count, must not exceed the **Bloom levels the
  curriculum analysis actually found** for a topic, and must sum to the
  requested total.
- **Cross-artifact consistency (→ `validation_errors`)** —
  `design_consistency_errors()`: when every allocation declares per-type
  counts, their aggregate must match the requested `type_mix`. A mismatch is
  structurally valid but contradicts the request, so it flows into
  `validation_errors`, which `quality_review` already turns into blockers —
  the reviewer sees it at the checkpoint instead of the run being killed.

## 5. Enabling it

```bash
AI_ENABLED=true
AI_USE_CURRICULUM_ANALYST=true    # provides the topics the designer needs
AI_USE_ASSESSMENT_DESIGNER=true   # assessment_design stage → the agent
```

Flag off (default) keeps the deterministic normalization handler
byte-for-byte; the switch happens in `configure_design_stage()` at
registration. Note the designer is only *useful* with the analyst enabled —
without topics it deliberately falls back to the skeleton.
