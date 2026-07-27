"""Structured-output contracts for agents (SDK output_type targets).

Reuses the platform's existing QuestionType/DifficultyLevel enums so an
agent literally cannot emit an off-vocabulary value — the schema rejects it
before any row is written (closes an audit §12 failure mode)."""
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from app.utils.constants import DifficultyLevel, QuestionType


class GeneratedOption(BaseModel):
    option_text: str
    is_correct: bool = False
    order_number: Optional[int] = None


class GeneratedQuestion(BaseModel):
    question_text: str
    question_type: QuestionType
    difficulty_level: DifficultyLevel = DifficultyLevel.MEDIUM
    points: float = Field(default=1.0, gt=0, le=999.99)
    order_number: Optional[int] = None
    options: Optional[List[GeneratedOption]] = None
    topic: Optional[str] = Field(
        default=None,
        description="Curriculum topic this question covers. Set only when the "
        "request supplies a topic allocation plan; it makes the blueprint's "
        "allocations verifiable. Not persisted on the exam row.",
    )


class GeneratedExamOutput(BaseModel):
    """What the exam_generator agent must return."""

    questions: List[GeneratedQuestion]


# ---------------------------------------------------------------- curriculum

class BloomLevel(str, Enum):
    REMEMBER = "remember"
    UNDERSTAND = "understand"
    APPLY = "apply"
    ANALYZE = "analyze"
    EVALUATE = "evaluate"
    CREATE = "create"


class TopicAnalysis(BaseModel):
    """One topic extracted from the teaching materials."""

    title: str = Field(min_length=1, max_length=255)
    subtopics: List[str] = []
    learning_outcomes: List[str] = Field(
        default=[], description="Observable outcomes, e.g. 'Students will be able to ...'"
    )
    bloom_levels: List[BloomLevel] = Field(
        default=[], description="Cognitive levels this topic exercises"
    )
    source_material_ids: List[str] = Field(
        default=[], description="Ids of the materials this topic was found in"
    )
    emphasis: str = Field(
        default="medium", pattern="^(low|medium|high)$",
        description="How heavily the materials emphasize this topic",
    )


class CurriculumAnalysisOutput(BaseModel):
    """What the curriculum_analyst agent must return: the ANALYTICAL half of
    the CurriculumOutline artifact (the inventory half — class, units,
    parseability — is deterministic and merged in by the stage handler)."""

    topics: List[TopicAnalysis]
    summary: str = Field(min_length=1, max_length=2000)


# ---------------------------------------------------------------- assessment design

class TopicAllocation(BaseModel):
    """How many questions a curriculum topic should receive, and of what
    cognitive/format shape. Scheduling (duration, dates) is explicitly NOT
    part of design — that is the Scheduler stage's artifact."""

    topic_title: str = Field(min_length=1, max_length=255)
    question_count: int = Field(ge=1, le=200)
    question_types: Dict[str, int] = Field(
        default={}, description="Optional per-type counts for this topic, e.g. {'mcq': 3}"
    )
    bloom_levels: List[BloomLevel] = Field(
        default=[], description="Cognitive levels these questions should target"
    )
    rationale: Optional[str] = Field(default=None, max_length=500)


class AssessmentDesignOutput(BaseModel):
    """What the assessment_designer agent must return: the DESIGN half of the
    AssessmentBlueprint artifact (the count skeleton — totals, type and
    difficulty mixes, points — is deterministic from the teacher's config and
    merged in by the stage handler)."""

    topic_allocations: List[TopicAllocation]
    rationale: str = Field(min_length=1, max_length=2000)


# ---------------------------------------------------------------- quality review

class QualityDimension(str, Enum):
    """The dimensions a quality review must cover."""

    COVERAGE = "coverage"
    DIFFICULTY_BALANCE = "difficulty_balance"
    QUESTION_DISTRIBUTION = "question_distribution"
    BLOOM_TAXONOMY = "bloom_taxonomy"
    INSTITUTION_POLICIES = "institution_policies"


class DimensionVerdict(BaseModel):
    """One dimension's outcome. 'not_assessable' is a legitimate, honest
    answer when the upstream artifacts carry no data for that dimension."""

    dimension: QualityDimension
    verdict: str = Field(pattern="^(pass|concerns|fail|not_assessable)$")
    comment: str = Field(min_length=1, max_length=1000)


class QualityObservation(BaseModel):
    """A single reviewer finding, attributed to a dimension. Note the
    reviewer can only ever ADD concerns — the deterministic pass/fail gate is
    never model-authored (see merge_quality_report)."""

    dimension: QualityDimension
    severity: str = Field(pattern="^(info|warning|blocker)$")
    message: str = Field(min_length=1, max_length=1000)


class QualityReviewOutput(BaseModel):
    """What the quality_reviewer agent must return: the REVIEW half of the
    QualityReport artifact (the deterministic structural checks and the
    authoritative `passed` flag are computed by the stage handler)."""

    dimension_verdicts: List[DimensionVerdict]
    observations: List[QualityObservation] = []
    summary: str = Field(min_length=1, max_length=2000)


# ---------------------------------------------------------------- difficulty analysis

class DifficultyCalibration(str, Enum):
    """How this exam's difficulty compares to the teacher's history."""

    ALIGNED = "aligned"
    EASIER = "easier"
    HARDER = "harder"
    UNCERTAIN = "uncertain"  # honest answer when there is no comparable history


class DifficultyAnalysisOutput(BaseModel):
    """What the difficulty_analyzer agent must return in LLM mode: the
    INTERPRETATION of statistics the handler already computed. It carries no
    distribution fields — the agent reads the numbers, it never rewrites the
    difficulty mix (that belongs to the teacher's config and the designer)."""

    calibration: DifficultyCalibration
    assessment: str = Field(min_length=1, max_length=2000)
    recommendations: List[str] = Field(default=[], max_length=10)


# ---------------------------------------------------------------- scheduling

class ScheduleReadiness(str, Enum):
    """Whether the proposed schedule is fit to go ahead."""

    READY = "ready"
    ADJUST = "adjust"                              # workable, but the teacher should change something
    BLOCKED = "blocked"                            # cannot run as proposed
    INSUFFICIENT_INFORMATION = "insufficient_information"  # no window was proposed


class SchedulePlanOutput(BaseModel):
    """What the scheduler agent must return: the ADVISORY half of the
    SchedulePlan artifact. The teacher's actual window and duration are
    deterministic config values the agent never overwrites — it may only
    *suggest* a duration, and it can never publish anything."""

    readiness: ScheduleReadiness
    rationale: str = Field(min_length=1, max_length=2000)
    recommendations: List[str] = Field(default=[], max_length=10)
    recommended_duration_minutes: Optional[int] = Field(
        default=None, gt=0, le=600,
        description="Optional suggestion only — it never replaces the teacher's duration",
    )
