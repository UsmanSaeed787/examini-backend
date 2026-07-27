# Curriculum Analyst Agent — Phase 6 of the Educational Agent OS

> The **first business agent**. Implemented in
> `backend/app/ai/agents/curriculum_analyst.py` + the assessment workflow's
> `CurriculumAnalystHandler`. It uses the AI Runtime for execution, the Tool
> Registry for data, the Context Engine for context, and returns **only
> structured output** — it never touches the database.

## 1. Responsibilities → implementation

| Brief | How |
|---|---|
| Read uploaded syllabus / analyze teaching materials | Text is prefetched per material via `MaterialService` + `ParserService` (deterministic, mirrors the generation facade) and delimited in the run input; the agent also holds `materials.list` / `materials.get_text` to re-read on demand |
| Extract topics | `TopicAnalysis.title` + `subtopics` |
| Identify learning outcomes | `TopicAnalysis.learning_outcomes` (observable phrasing, enforced by instructions + guardrail non-emptiness) |
| Estimate Bloom's taxonomy levels | `TopicAnalysis.bloom_levels: List[BloomLevel]` — a closed enum (remember…create), so an off-vocabulary level fails schema validation before it can reach an artifact |
| Produce a structured `CurriculumOutline` artifact | The stage handler merges the agent's analysis into the deterministic inventory (see §3) |
| Integrate with Assessment Intelligence | Registered as the `curriculum_analysis` stage handler behind `AI_USE_CURRICULUM_ANALYST` |

## 2. Stack usage (no shortcuts taken)

- **Runtime**: the stage handler calls `runner.execute_run(...)` — quotas,
  timeout, retry, cancellation, usage/cost recording, and events all apply,
  and the produced `run_id` is written to `ai_workflow_stages.run_id`, so
  every agent-authored artifact is traceable to its run.
- **Tool Registry**: tools resolved by key with `sdk_tools(*REQUIRED_TOOLS)`;
  registration validates that a teacher is granted both permissions. **No
  SQLAlchemy import exists in the agent module.**
- **Context Engine**: the handler seeds `workflow_id`, `stage`, and
  `class_id` in the run identity's `extra`, so the pre-flight snapshot
  carries the workflow, stage, artifacts, and course facets.
- **Structured output only**: `AgentOutputSchema(CurriculumAnalysisOutput,
  strict_json_schema=False)` (Gemini-compat), plus an output guardrail.

## 3. The hybrid stage: deterministic facts + agent analysis

`CurriculumOutline` has two halves, and the split is deliberate:

- **Inventory** (class, units, parseability, findings) — always computed by
  the deterministic code path. The model cannot author facts about which
  materials exist or whether they are readable.
- **Analysis** (`topics`, `summary`) — the agent's contribution, merged in by
  `merge_outline()` via `model_copy(update=...)`.

Both fields are additive, so the deterministic v1 handler and the agent
handler satisfy one artifact contract (verified by test).

**Fallbacks** (cheap and honest): if the inventory has blockers, or nothing
is parseable, or no text could be extracted, the stage returns the
inventory-only outline without spending tokens on a stage the reviewer must
reject anyway. Per-material extraction failures degrade to a `warning`
finding naming the skipped materials. An actual agent failure fails the
stage visibly (workflow → FAILED) rather than silently degrading.

**Revision loop**: on checkpoint rejection the reviewer's notes are fed back
into the next run's input (and Phase 5 already stores them as workflow
memory), so revisions are informed rather than blind retries.

## 4. Output guardrail

`validate_curriculum_analysis()` (pure, unit-tested) rejects: empty
analysis; a topic with no learning outcomes; a topic with no Bloom levels;
and **cited source material ids outside the provided set** — the agent
cannot invent sources. Tripwires surface as `AI_GUARDRAIL_REJECTED`.

## 5. Enabling it

```bash
AI_ENABLED=true
AI_USE_CURRICULUM_ANALYST=true   # curriculum_analysis stage → the agent
```
Flag off (default) keeps the deterministic handler byte-for-byte; the switch
happens in `configure_curriculum_stage()` at registration, so no workflow,
orchestrator, or API code changes either way.
