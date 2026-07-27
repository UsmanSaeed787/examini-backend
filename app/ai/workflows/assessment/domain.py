"""Domain vocabulary for the Assessment Intelligence workflow."""
from enum import Enum


class StageKey(str, Enum):
    """Pipeline stages. Each maps 1:1 to a future specialist agent."""

    CURRICULUM_ANALYSIS = "curriculum_analysis"    # Curriculum Analyst
    ASSESSMENT_DESIGN = "assessment_design"        # Assessment Designer
    QUALITY_REVIEW = "quality_review"              # Quality Reviewer
    DIFFICULTY_ANALYSIS = "difficulty_analysis"    # Difficulty Analyzer
    SCHEDULING = "scheduling"                      # Scheduler


# Canonical execution order. The orchestrator only knows this list; adding a
# stage = add enum member + handler + insert here.
DEFAULT_PIPELINE: tuple[StageKey, ...] = (
    StageKey.CURRICULUM_ANALYSIS,
    StageKey.ASSESSMENT_DESIGN,
    StageKey.QUALITY_REVIEW,
    StageKey.DIFFICULTY_ANALYSIS,
    StageKey.SCHEDULING,
)


class WorkflowState(str, Enum):
    DRAFT = "draft"                        # created, not started
    IN_PROGRESS = "in_progress"            # a stage is pending/running
    AWAITING_APPROVAL = "awaiting_approval"  # current stage is in human review
    COMPLETED = "completed"                # all stages approved; result assembled
    CANCELLED = "cancelled"
    FAILED = "failed"


TERMINAL_STATES = frozenset(
    {WorkflowState.COMPLETED, WorkflowState.CANCELLED, WorkflowState.FAILED}
)


class StageStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    IN_REVIEW = "in_review"    # artifact produced, waiting for human checkpoint
    APPROVED = "approved"
    REJECTED = "rejected"      # transient; immediately re-queued as PENDING (revision+1)
    FAILED = "failed"


class ApprovalMode(str, Enum):
    """Checkpoint policy chosen at workflow creation."""

    EVERY_STAGE = "every_stage"  # human approves after each stage (default)
    FINAL_ONLY = "final_only"    # human approves only the last stage
    NONE = "none"                # fully automatic (stages auto-approve)


class CheckpointDecision(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"
    # The teacher changed the question mix themselves. Distinct from REJECTED:
    # nothing is being asked of the model, the affected stages are simply
    # recomputed from the new numbers.
    ADJUSTED = "adjusted"


# Stages recomputed when the question mix changes. Curriculum analysis is
# excluded on purpose — the materials did not change, so re-reading them would
# spend a model call to reproduce the same inventory.
ADJUSTABLE_FROM: StageKey = StageKey.ASSESSMENT_DESIGN

# Reserved config key marking a run as deterministic-only. It travels in the
# workflow config because the pipeline runs detached, so it must outlive the
# request that set it.
DETERMINISTIC_RERUN_KEY = "_deterministic_rerun"


class GenerationStatus(str, Enum):
    """Materialization lifecycle: an approved AssessmentPlan becoming a real,
    published exam. Deliberately separate from WorkflowState — the planning
    pipeline still ends at COMPLETED (a terminal state), and materialization
    is a downstream consumer of that result, not a sixth stage."""

    PENDING = "pending"          # attempt row created, generation not started
    GENERATING = "generating"    # agent run in flight
    GENERATED = "generated"      # questions written to a DRAFT (unpublished) exam
    PUBLISHED = "published"      # a human released it to students
    FAILED = "failed"
    SUPERSEDED = "superseded"    # a later attempt replaced this one


# Publishing is the one transition a model can never make: it is only ever
# reached from GENERATED, and only by an explicit human request (see
# materialization.publish_assessment).
GENERATION_TRANSITIONS: dict[GenerationStatus, frozenset[GenerationStatus]] = {
    GenerationStatus.PENDING: frozenset(
        {GenerationStatus.GENERATING, GenerationStatus.FAILED, GenerationStatus.SUPERSEDED}
    ),
    GenerationStatus.GENERATING: frozenset(
        {GenerationStatus.GENERATED, GenerationStatus.FAILED}
    ),
    GenerationStatus.GENERATED: frozenset(
        {GenerationStatus.PUBLISHED, GenerationStatus.SUPERSEDED}
    ),
    GenerationStatus.PUBLISHED: frozenset(),   # terminal: never regenerated over
    GenerationStatus.FAILED: frozenset({GenerationStatus.SUPERSEDED}),
    GenerationStatus.SUPERSEDED: frozenset(),
}
