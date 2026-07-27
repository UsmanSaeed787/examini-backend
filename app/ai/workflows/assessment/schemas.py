"""Contracts for the Assessment Intelligence workflow.

Two families:
1. STAGE ARTIFACTS — the typed output each stage must produce. These are the
   plug-in contract for future specialist agents: an agent-backed handler
   must emit the same artifact model its deterministic predecessor does
   (they become SDK structured-output targets unchanged).
2. API DTOs — request/response shapes for /api/ai/workflows/assessment.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.ai.schemas.outputs import DimensionVerdict, TopicAllocation, TopicAnalysis
from app.ai.workflows.assessment.domain import (
    ApprovalMode,
    GenerationStatus,
    StageKey,
    StageStatus,
    WorkflowState,
)


# ================================================================ artifacts

class Finding(BaseModel):
    """A single observation raised by any stage."""

    severity: str = Field(pattern="^(info|warning|blocker)$")
    message: str
    stage: StageKey


class CurriculumUnit(BaseModel):
    material_id: str
    title: str
    file_type: Optional[str] = None
    file_size: Optional[int] = None
    parseable: bool  # pdf/docx/txt can feed text-based agents; others cannot


class CurriculumOutline(BaseModel):
    """Artifact of curriculum_analysis.

    Two halves: the deterministic INVENTORY (class, units, parseability —
    always present) and the ANALYSIS (topics/summary — filled by the
    Curriculum Analyst agent when enabled; empty under the deterministic
    v1 handler). Additive fields keep both handlers on one contract."""

    class_id: str
    class_name: str
    units: List[CurriculumUnit]
    missing_material_ids: List[str] = []
    findings: List[Finding] = []
    topics: List[TopicAnalysis] = []
    summary: Optional[str] = None


class AssessmentBlueprint(BaseModel):
    """Artifact of assessment_design.

    Two halves: the deterministic COUNT SKELETON (totals, type/difficulty
    mixes, points — derived from the teacher's question_config and never
    model-authored) and the DESIGN (topic allocations + rationale, filled by
    the Assessment Designer agent when enabled; empty under the
    deterministic v1 handler). Additive fields keep both handlers on one
    contract. Scheduling never appears here — that is SchedulePlan."""

    total_questions: int
    type_mix: Dict[str, int] = {}        # mcq/short_answer/long_answer/true_false -> count
    difficulty_mix: Dict[str, int] = {}  # easy/medium/hard -> count
    default_points: float = 1.0
    estimated_total_points: float
    validation_errors: List[str] = []    # structural problems, surfaced to quality_review
    topic_allocations: List[TopicAllocation] = []
    rationale: Optional[str] = None


class QualityReport(BaseModel):
    """Artifact of quality_review.

    `passed` and the structural findings are deterministic and authoritative;
    the Quality Reviewer agent contributes per-dimension verdicts, extra
    observations, and a summary. The agent can add blockers but can never
    clear one (see merge_quality_report)."""

    passed: bool
    findings: List[Finding] = []
    dimension_verdicts: List[DimensionVerdict] = []
    summary: Optional[str] = None


class ExamComparison(BaseModel):
    """One of the teacher's previous exams, for difficulty comparison.
    Deterministic — computed from the platform's own records."""

    exam_id: str
    title: str
    question_count: int
    difficulty_counts: Dict[str, int] = {}
    difficulty_index: Optional[float] = None   # 1.0 (all easy) .. 3.0 (all hard)
    average_percentage: Optional[float] = None  # how students actually scored
    result_count: int = 0


class DifficultyProfile(BaseModel):
    """Artifact of difficulty_analysis.

    The statistics half (distributions, indices, divergence, per-exam
    comparisons, notes) is always computed deterministically. In LLM mode the
    Difficulty Analyzer adds interpretation (calibration, assessment,
    recommendations) on top of exactly those numbers."""

    target_distribution: Dict[str, float] = {}      # easy/medium/hard -> fraction 0..1
    historical_distribution: Dict[str, float] = {}  # from the teacher's past exams
    historical_question_count: int = 0
    notes: List[str] = []
    mode: str = "deterministic"                     # deterministic | llm
    difficulty_index: Optional[float] = None        # this exam, 1.0..3.0
    historical_difficulty_index: Optional[float] = None
    divergence: Optional[float] = None              # 0.0 (identical) .. 1.0 (disjoint)
    exam_comparisons: List[ExamComparison] = []
    calibration: Optional[str] = None               # aligned | easier | harder | uncertain
    assessment: Optional[str] = None
    recommendations: List[str] = []


class ScheduleConflict(BaseModel):
    """Another exam for the same class whose window overlaps this one.

    This is the platform's available 'academic calendar' signal — Examini has
    no institutional calendar of terms/holidays (see SCHEDULER_DESIGN.md)."""

    exam_id: str
    title: str
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    overlap_minutes: Optional[float] = None
    is_published: bool = False


class SchedulePlan(BaseModel):
    """Artifact of scheduling.

    The teacher's constraints (window, duration), the duration estimate, and
    calendar conflicts are deterministic. When the Scheduler agent is
    enabled it adds an advisory half (readiness, rationale,
    recommendations, a suggested duration). Nothing here publishes an exam."""

    duration_minutes: Optional[int] = None
    proposed_start: Optional[datetime] = None
    proposed_end: Optional[datetime] = None
    findings: List[Finding] = []
    estimated_duration_minutes: Optional[int] = None   # from the blueprint's question mix
    duration_basis: Dict[str, float] = {}              # per-type minutes used for the estimate
    window_minutes: Optional[float] = None
    conflicts: List[ScheduleConflict] = []
    readiness: Optional[str] = None                    # ready | adjust | blocked | insufficient_information
    rationale: Optional[str] = None
    recommendations: List[str] = []
    recommended_duration_minutes: Optional[int] = None  # suggestion only, never applied


ARTIFACT_TYPES: dict[StageKey, type[BaseModel]] = {
    StageKey.CURRICULUM_ANALYSIS: CurriculumOutline,
    StageKey.ASSESSMENT_DESIGN: AssessmentBlueprint,
    StageKey.QUALITY_REVIEW: QualityReport,
    StageKey.DIFFICULTY_ANALYSIS: DifficultyProfile,
    StageKey.SCHEDULING: SchedulePlan,
}


class AssessmentPlan(BaseModel):
    """Final workflow result: the approved plan a future question-generation
    phase (Assessment Designer agent) will materialize into an exam."""

    workflow_id: str
    title: str
    class_id: str
    outline: CurriculumOutline
    blueprint: AssessmentBlueprint
    quality: QualityReport
    difficulty: DifficultyProfile
    schedule: SchedulePlan
    approved_at: datetime


# ================================================================ API DTOs

class CreateWorkflowRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    class_id: UUID
    material_ids: List[UUID] = Field(min_length=1)
    question_config: Dict[str, Any]
    duration_minutes: Optional[int] = Field(default=None, gt=0)
    proposed_start: Optional[datetime] = None
    proposed_end: Optional[datetime] = None
    approval_mode: ApprovalMode = ApprovalMode.EVERY_STAGE


class ApproveRequest(BaseModel):
    notes: Optional[str] = Field(default=None, max_length=2000)


class RejectRequest(BaseModel):
    notes: str = Field(min_length=1, max_length=2000)
    # Optional corrections applied to the workflow config before the stage
    # re-runs (e.g. a fixed question_config).
    config_patch: Optional[Dict[str, Any]] = None


class AdjustMixRequest(BaseModel):
    """A teacher's own edit to the question mix.

    No notes field: rejection needs prose because it asks the AI to reconsider;
    an adjustment states the numbers, which speak for themselves."""

    question_config: Dict[str, Any]


class StageResponse(BaseModel):
    stage_key: StageKey
    sequence: int
    status: StageStatus
    revision: int
    requires_checkpoint: bool
    artifact: Optional[Dict[str, Any]] = None
    notes: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class WorkflowResponse(BaseModel):
    id: UUID
    title: str
    state: WorkflowState
    current_stage: Optional[StageKey] = None
    approval_mode: ApprovalMode
    class_id: UUID
    config: Dict[str, Any]
    stages: List[StageResponse]
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    created_at: datetime
    finished_at: Optional[datetime] = None


class WorkflowSummaryResponse(BaseModel):
    id: UUID
    title: str
    state: WorkflowState
    current_stage: Optional[StageKey] = None
    created_at: datetime


# ================================================================ materialization

class PublishRequest(BaseModel):
    """Explicit human confirmation. `acknowledge_findings` must be true when
    the generated exam carries unresolved validation findings — the teacher
    releases it knowingly or not at all."""

    acknowledge_findings: bool = False


class GenerationResponse(BaseModel):
    """State of the workflow's materialization: the approved plan becoming a
    real exam students can sit."""

    workflow_id: UUID
    status: GenerationStatus
    attempt: int
    exam_id: Optional[UUID] = None
    run_id: Optional[UUID] = None
    question_count: int = 0
    findings: List[str] = []
    error: Optional[str] = None
    is_published: bool = False
    created_at: Optional[datetime] = None
    generated_at: Optional[datetime] = None
    published_at: Optional[datetime] = None


class GenerationHistoryResponse(BaseModel):
    """Full audit trail: every materialization attempt for this workflow,
    newest first, with `current` pointing at the live one."""

    workflow_id: UUID
    current: Optional[GenerationResponse] = None
    attempts: List[GenerationResponse] = []
