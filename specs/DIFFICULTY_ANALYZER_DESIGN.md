# Difficulty Analyzer — Phase 9 of the Educational Agent OS

> The **fourth business agent**, and the first stage built around two
> first-class execution *modes*. Implemented in
> `backend/app/ai/agents/difficulty_analyzer.py` plus the deterministic core
> and both handlers in the assessment workflow's `stages.py`.

## 1. Two modes, one artifact

Phase 9 requires the stage to support **deterministic mode and future LLM
mode**, so the mode is modelled explicitly rather than as another on/off
agent flag:

```bash
AI_DIFFICULTY_ANALYSIS_MODE=deterministic   # default: statistics only, no model
AI_DIFFICULTY_ANALYSIS_MODE=llm             # same statistics + agent interpretation
```

`configure_difficulty_stage()` selects the handler at registration; an
unrecognized value falls back to deterministic (tested). Both modes produce
the same `DifficultyProfile` artifact, and `profile.mode` records which one
ran, so a consumer can always tell.

## 2. Deterministic mode is a real analysis, not a placeholder

The pure core (no I/O, no model — fully unit-tested) computes:

| Output | Meaning |
|---|---|
| `target_distribution` / `historical_distribution` | difficulty fractions for this exam vs the teacher's recent exams |
| `difficulty_index` / `historical_difficulty_index` | weighted mean difficulty on a **1.0 (all easy) … 3.0 (all hard)** scale — one number that makes exams comparable |
| `divergence` | total variation distance between the two distributions, 0.0 identical … 1.0 disjoint |
| `exam_comparisons` | per previous exam: title, question count, difficulty composition, its index, **and how students actually scored** |
| `notes` | plain-language flags: per-level gaps ≥ 25 %, an overall index gap ≥ 0.3 ("this exam looks harder than your recent average"), student averages, and an explicit statement when there is no history |

**Comparing against previous exams** uses the teacher's 10 most recent exams
and joins their results in **one aggregate query** (`ExamAttempt` →
`ExamResult`, grouped by exam) — no N+1, and the outcome data means the
comparison is against how difficulty actually *landed*, not just how it was
labelled.

## 3. LLM mode adds interpretation, never numbers

`DifficultyAnalyzerHandler` runs the identical deterministic analysis first,
then hands those statistics to the agent, which returns only:

- `calibration` — `aligned` / `easier` / `harder` / `uncertain`
- `assessment` — what the numbers mean for students taking this exam
- `recommendations` — concrete actions when the exam diverges

`merge_difficulty_profile()` copies these onto the profile and touches
nothing else; every distribution, index, divergence value and note stays
exactly as computed (asserted by test). The output model deliberately has
**no distribution fields**, so the agent structurally cannot rewrite the
difficulty mix it is commenting on.

## 4. Guardrail: two honesty rules

- A comparison cannot be claimed against nothing: with no history, the
  calibration must be `uncertain` (the handler also states this in the
  prompt and passes `has_history` for the guardrail).
- A divergence must be actionable: `easier`/`harder` requires at least one
  recommendation.

`aligned` and `uncertain` need no recommendations, so the agent is never
pushed into inventing advice.

## 5. Constraints honoured

- **No database access** — zero tools; all statistics arrive in the run input.
- **No redesign** — it interprets; the mix belongs to the teacher's config
  and the Assessment Designer.
- **No orchestration or scheduling** — no vocabulary for either.
- LLM mode skips the agent entirely when the blueprint has no difficulty mix
  (nothing to interpret), returning the deterministic profile.

## 6. Enabling it

```bash
AI_ENABLED=true
AI_DIFFICULTY_ANALYSIS_MODE=llm
```

Deterministic mode needs no AI configuration at all — it is the default and
works with the AI layer switched off entirely.
