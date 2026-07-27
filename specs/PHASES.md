# Phase 2 — Agent Registry

Design and implement a dynamic Agent Registry for the Educational Agent OS.

The registry should discover, register, version, enable/disable, and execute AI agents without changing workflow code.

Support metadata, capabilities, required tools, supported workflows, permissions, model configuration, and structured outputs.

Do not implement any business agents yet.

# Phase 3 — Tool Registry

Design and implement a Tool Registry that wraps existing backend services.

Agents must never access SQLAlchemy or the database directly.

Every interaction must occur through reusable tools.

Create tool interfaces, registration, permissions, validation, execution pipeline, and dependency injection.

Reuse existing services such as:

MaterialService
ExamService
StudentService
TeacherService
ClassService
ResultService

Do not duplicate business logic.

# Phase 4 — Context Engine

Design and implement the AI Context Engine.

The Context Engine should build the complete execution context before an agent runs.

It should collect:

Authenticated user

Current workflow

Current stage

Artifacts

Conversation history

Institution settings

Academic policies

Course information

Permissions

Previous outputs

Knowledge references

The Context Engine must return a strongly typed immutable context object consumed by every future agent.

No LLM logic should exist here.

# Phase 5 — Memory Layer

Design and implement the AI Memory Layer.

Support:

Workflow Memory

Session Memory

Conversation Memory

Artifact Memory

Agent Memory

Short-term Memory

Long-term Memory (future)

Memory retrieval

Memory persistence

Memory interfaces

The implementation must remain provider-independent.

# Phase 6 — Curriculum Analyst Agent

Implement the Curriculum Analyst Agent.

Responsibilities:

Read uploaded syllabus

Analyze teaching materials

Extract topics

Identify learning outcomes

Estimate Bloom's Taxonomy levels

Produce a structured CurriculumOutline artifact

Use the AI Runtime.

Use the Tool Registry.

Use the Context Engine.

Do not access the database directly.

Return only structured outputs.

Integrate with the Assessment Intelligence workflow.

# Phase 7 — Assessment Designer

Implement Assessment Designer Agent.

Consumes CurriculumOutline.

Produces AssessmentBlueprint.

Uses AI Runtime.

No database access.

No workflow logic.

No scheduling.

# Phase 8 — Quality Reviewer

Implement Quality Reviewer Agent.

Consumes AssessmentBlueprint.

Checks:

Coverage

Difficulty balance

Question distribution

Bloom's Taxonomy

Institution policies

Returns QualityReport.

No workflow orchestration.

# Phase 9 — Difficulty Analyzer

Implement Difficulty Analyzer Agent.

Analyze blueprint difficulty.

Compare against previous exams.

Produce DifficultyProfile.

Support deterministic mode and future LLM mode.

# Phase 10 — Scheduler

Implement Scheduler Agent.

Analyze teacher constraints.

Analyze academic calendar.

Analyze duration.

Produce SchedulePlan.

No publishing.
