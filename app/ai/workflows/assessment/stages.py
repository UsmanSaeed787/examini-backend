"""Stage handlers: the workflow's plug-in surface.

A handler receives a StageContext (no live DB session — handlers own their
I/O like tools do) and returns the stage's typed artifact. v1 handlers are
DETERMINISTIC: they orchestrate reads through existing services and pure
computations — no LLM calls, no question generation, no duplicated business
logic.

Replacing any stage with a specialist agent later means registering
    AgentStageHandler(StageKey.X, agent_key="curriculum_analyst")
instead of the deterministic handler — the orchestrator, schemas, API, and
approval flow do not change (the artifact model is the contract).
"""
import asyncio
from abc import ABC, abstractmethod
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel

from app.ai.guardrails.input import validate_question_config
from app.ai.tools._base import db_session
from app.ai.workflows.assessment.domain import DEFAULT_PIPELINE, StageKey
from app.ai.workflows.assessment.schemas import (
    ARTIFACT_TYPES,
    AssessmentBlueprint,
    CurriculumOutline,
    CurriculumUnit,
    DifficultyProfile,
    ExamComparison,
    Finding,
    QualityReport,
    ScheduleConflict,
    SchedulePlan,
)
from app.middleware.error_handler import ValidationError

_PARSEABLE_TYPES = {"pdf", "docx", "txt"}


@dataclass
class StageContext:
    """Everything a handler may use. Prior artifacts are plain dicts keyed by
    stage value, so handlers (and future agents) read upstream output without
    touching workflow persistence."""

    workflow_id: UUID
    user_id: UUID
    role: str
    class_id: UUID
    config: dict
    revision: int
    prior_artifacts: Dict[str, dict] = field(default_factory=dict)
    rejection_notes: Optional[str] = None
    # Set by agent-backed handlers so the orchestrator can link the stage row
    # to the ai_runs record that produced its artifact.
    run_id: Optional[UUID] = None
    # True when the teacher adjusted the question mix themselves. The numbers
    # changed, not the request — so agent-backed handlers recompute from their
    # deterministic core instead of spending a model call to re-narrate the
    # same decision. Agent commentary is dropped rather than left stale.
    deterministic_only: bool = False


class StageHandler(ABC):
    key: StageKey

    @abstractmethod
    async def execute(self, ctx: StageContext) -> BaseModel:
        """Produce this stage's artifact (must be ARTIFACT_TYPES[self.key])."""


# ============================================================ deterministic v1

class CurriculumAnalysisHandler(StageHandler):
    """Curriculum Analyst seam — v1: factual material/class inventory."""

    key = StageKey.CURRICULUM_ANALYSIS

    async def execute(self, ctx: StageContext) -> CurriculumOutline:
        return await asyncio.to_thread(self._run, ctx)

    @staticmethod
    def _run(ctx: StageContext) -> CurriculumOutline:
        from app.services.class_service import ClassService
        from app.services.material_service import MaterialService

        requested = [UUID(m) for m in ctx.config.get("material_ids", [])]
        with db_session() as db:
            cls = ClassService.get_class(db, ctx.class_id)
            materials = MaterialService.get_materials_by_ids(db, requested, ctx.user_id)
            found_ids = {m.id for m in materials}
            missing = [str(m) for m in requested if m not in found_ids]
            units = [
                CurriculumUnit(
                    material_id=str(m.id),
                    title=m.title,
                    file_type=m.file_type,
                    file_size=m.file_size,
                    parseable=(m.file_type or "").lower() in _PARSEABLE_TYPES,
                )
                for m in materials
            ]
        findings = []
        if missing:
            findings.append(
                Finding(
                    severity="blocker",
                    message=f"{len(missing)} selected material(s) not found or not owned by you",
                    stage=StageKey.CURRICULUM_ANALYSIS,
                )
            )
        for unit in units:
            if not unit.parseable:
                findings.append(
                    Finding(
                        severity="warning",
                        message=f"Material '{unit.title}' ({unit.file_type}) has no extractable text",
                        stage=StageKey.CURRICULUM_ANALYSIS,
                    )
                )
        return CurriculumOutline(
            class_id=str(ctx.class_id),
            class_name=cls.name,
            units=units,
            missing_material_ids=missing,
            findings=findings,
        )


def normalize_blueprint(question_config: dict) -> AssessmentBlueprint:
    """Pure normalization of the teacher's question_config into a blueprint."""
    errors = validate_question_config(question_config or {})
    total = question_config.get("total") if isinstance(question_config, dict) else None
    total = int(total) if isinstance(total, int) and not isinstance(total, bool) else 0
    type_mix = {
        k: int(question_config[k])
        for k in ("mcq", "short_answer", "long_answer", "true_false")
        if isinstance(question_config.get(k), int) and not isinstance(question_config.get(k), bool)
    }
    difficulty_mix = {
        k: int(question_config[k])
        for k in ("easy", "medium", "hard")
        if isinstance(question_config.get(k), int) and not isinstance(question_config.get(k), bool)
    }
    default_points = float(question_config.get("points_per_question") or 1.0)
    return AssessmentBlueprint(
        total_questions=max(total, 0),
        type_mix=type_mix,
        difficulty_mix=difficulty_mix,
        default_points=default_points,
        estimated_total_points=max(total, 0) * default_points,
        validation_errors=errors,
    )


class AssessmentDesignHandler(StageHandler):
    """Assessment Designer seam — v1: deterministic blueprint normalization."""

    key = StageKey.ASSESSMENT_DESIGN

    async def execute(self, ctx: StageContext) -> AssessmentBlueprint:
        return normalize_blueprint(ctx.config.get("question_config") or {})


def review_quality(
    outline: CurriculumOutline, blueprint: AssessmentBlueprint
) -> QualityReport:
    """Pure quality checks over upstream artifacts."""
    findings: list[Finding] = list(outline.findings)
    for error in blueprint.validation_errors:
        findings.append(
            Finding(severity="blocker", message=error, stage=StageKey.QUALITY_REVIEW)
        )
    parseable_count = sum(1 for u in outline.units if u.parseable)
    if parseable_count == 0:
        findings.append(
            Finding(
                severity="blocker",
                message="No selected material has extractable text to base questions on",
                stage=StageKey.QUALITY_REVIEW,
            )
        )
    if blueprint.total_questions > 0 and parseable_count > 0:
        per_material = blueprint.total_questions / parseable_count
        if per_material > 25:
            findings.append(
                Finding(
                    severity="warning",
                    message=(
                        f"{blueprint.total_questions} questions from {parseable_count} "
                        "material(s) may spread coverage thin"
                    ),
                    stage=StageKey.QUALITY_REVIEW,
                )
            )
    passed = not any(f.severity == "blocker" for f in findings)
    return QualityReport(passed=passed, findings=findings)


class QualityReviewHandler(StageHandler):
    """Quality Reviewer seam — v1: deterministic consistency checks."""

    key = StageKey.QUALITY_REVIEW

    async def execute(self, ctx: StageContext) -> QualityReport:
        outline = CurriculumOutline(**ctx.prior_artifacts[StageKey.CURRICULUM_ANALYSIS.value])
        blueprint = AssessmentBlueprint(**ctx.prior_artifacts[StageKey.ASSESSMENT_DESIGN.value])
        return review_quality(outline, blueprint)


# ---------------- deterministic difficulty core (pure, unit-testable) ----------------

DIFFICULTY_WEIGHTS = {"easy": 1.0, "medium": 2.0, "hard": 3.0}
DIVERGENCE_NOTE_THRESHOLD = 0.25   # per-level fraction gap worth flagging
INDEX_NOTE_THRESHOLD = 0.3         # difficulty-index gap worth flagging
HISTORY_EXAM_LIMIT = 10


@dataclass(frozen=True)
class HistoricalDifficulty:
    """The teacher's recent exams, summarized for comparison."""

    counts: Dict[str, int] = field(default_factory=dict)
    total: int = 0
    exams: tuple = ()                       # ExamComparison
    average_percentage: Optional[float] = None


def as_distribution(counts: Dict[str, int]) -> Dict[str, float]:
    total = sum(counts.values())
    return {k: round(v / total, 3) for k, v in counts.items()} if total else {}


def difficulty_index(counts: Dict[str, int]) -> Optional[float]:
    """Weighted mean difficulty on a 1.0 (all easy) .. 3.0 (all hard) scale."""
    total = sum(counts.values())
    if not total:
        return None
    weighted = sum(DIFFICULTY_WEIGHTS.get(level, 0.0) * n for level, n in counts.items())
    return round(weighted / total, 2)


def distribution_divergence(a: Dict[str, float], b: Dict[str, float]) -> Optional[float]:
    """Total variation distance between two distributions: 0.0 identical,
    1.0 completely disjoint."""
    if not a or not b:
        return None
    keys = set(a) | set(b)
    return round(0.5 * sum(abs(a.get(k, 0.0) - b.get(k, 0.0)) for k in keys), 3)


def build_difficulty_profile(
    blueprint: AssessmentBlueprint, history: HistoricalDifficulty
) -> DifficultyProfile:
    """Deterministic analysis: this exam's difficulty vs the teacher's own
    history. Pure — no I/O, no model."""
    target = as_distribution(blueprint.difficulty_mix)
    historical = as_distribution(history.counts)
    target_index = difficulty_index(blueprint.difficulty_mix)
    historical_index = difficulty_index(history.counts)
    divergence = distribution_divergence(target, historical)

    notes: List[str] = []
    if not history.total:
        notes.append(
            "No previous exams with difficulty labels were found, so this exam "
            "cannot be compared against your history."
        )
    if not target:
        notes.append("The blueprint requests no difficulty mix, so the target profile is unknown.")

    for level, target_fraction in target.items():
        historical_fraction = historical.get(level, 0.0)
        if history.total and abs(target_fraction - historical_fraction) >= DIVERGENCE_NOTE_THRESHOLD:
            notes.append(
                f"'{level}' target ({target_fraction:.0%}) differs notably from your "
                f"historical exams ({historical_fraction:.0%})"
            )

    if target_index is not None and historical_index is not None:
        gap = target_index - historical_index
        if abs(gap) >= INDEX_NOTE_THRESHOLD:
            direction = "harder" if gap > 0 else "easier"
            notes.append(
                f"Overall this exam looks {direction} than your recent average "
                f"(difficulty index {target_index} vs {historical_index})."
            )
    if history.average_percentage is not None:
        notes.append(
            f"Students averaged {history.average_percentage:.0f}% across your "
            f"{len(history.exams)} most recent exam(s)."
        )

    return DifficultyProfile(
        target_distribution=target,
        historical_distribution=historical,
        historical_question_count=history.total,
        notes=notes,
        mode="deterministic",
        difficulty_index=target_index,
        historical_difficulty_index=historical_index,
        divergence=divergence,
        exam_comparisons=list(history.exams),
    )


def load_historical_difficulty(
    teacher_id: UUID, limit: int = HISTORY_EXAM_LIMIT
) -> HistoricalDifficulty:
    """Summarize the teacher's most recent exams: difficulty composition and
    how students actually scored. One aggregate query for results (no N+1)."""
    from sqlalchemy import func

    from app.models.attempt import ExamAttempt, ExamResult
    from app.services.exam_service import ExamService

    with db_session() as db:
        exams = ExamService.get_exams(db, teacher_id=teacher_id)
        exams = sorted(exams, key=lambda e: e.created_at or datetime.min, reverse=True)[:limit]
        if not exams:
            return HistoricalDifficulty()

        outcomes = {
            exam_id: (float(avg) if avg is not None else None, int(count))
            for exam_id, avg, count in db.query(
                ExamAttempt.exam_id,
                func.avg(ExamResult.percentage),
                func.count(ExamResult.id),
            )
            .join(ExamResult, ExamResult.attempt_id == ExamAttempt.id)
            .filter(ExamAttempt.exam_id.in_([e.id for e in exams]))
            .group_by(ExamAttempt.exam_id)
            .all()
        }

        overall: Counter = Counter()
        comparisons = []
        for exam in exams:
            counts: Counter = Counter()
            for question in exam.questions:
                if question.difficulty_level:
                    counts[question.difficulty_level] += 1
            overall.update(counts)
            average, result_count = outcomes.get(exam.id, (None, 0))
            comparisons.append(
                ExamComparison(
                    exam_id=str(exam.id),
                    title=exam.title,
                    question_count=len(exam.questions),
                    difficulty_counts=dict(counts),
                    difficulty_index=difficulty_index(dict(counts)),
                    average_percentage=round(average, 1) if average is not None else None,
                    result_count=result_count,
                )
            )

    scored = [c.average_percentage for c in comparisons if c.average_percentage is not None]
    return HistoricalDifficulty(
        counts=dict(overall),
        total=sum(overall.values()),
        exams=tuple(comparisons),
        average_percentage=round(sum(scored) / len(scored), 1) if scored else None,
    )


class DifficultyAnalysisHandler(StageHandler):
    """Difficulty Analyzer — DETERMINISTIC mode (the default).

    Computes the full statistical profile with no model involvement; this is
    a complete analysis in its own right, not a placeholder."""

    key = StageKey.DIFFICULTY_ANALYSIS

    async def execute(self, ctx: StageContext) -> DifficultyProfile:
        blueprint = AssessmentBlueprint(**ctx.prior_artifacts[StageKey.ASSESSMENT_DESIGN.value])
        history = await asyncio.to_thread(load_historical_difficulty, ctx.user_id)
        return build_difficulty_profile(blueprint, history)


# ---------------- deterministic scheduling core (pure, unit-testable) ----------------

# Minutes a typical student needs per question, by type. Used only to
# ESTIMATE a sensible duration — it never overrides the teacher's setting.
QUESTION_MINUTES = {"mcq": 1.5, "true_false": 1.0, "short_answer": 4.0, "long_answer": 10.0}
DEFAULT_MINUTES_PER_QUESTION = 2.0
UNDER_DURATION_RATIO = 0.75  # requested duration below this share of the estimate is flagged


def _as_aware_utc(value) -> Optional[datetime]:
    """Parse ISO strings / normalize datetimes to aware UTC.

    Naive values are treated as UTC so window arithmetic never mixes naive
    and aware datetimes (the comparison bug the audit flagged elsewhere)."""
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def estimate_exam_duration(blueprint: Optional[AssessmentBlueprint]) -> tuple[Optional[int], dict]:
    """Estimate the minutes an exam needs from its question mix.
    Returns (minutes, basis) where basis records the per-type rates used."""
    if blueprint is None:
        return None, {}
    if blueprint.type_mix:
        minutes = sum(
            QUESTION_MINUTES.get(q_type, DEFAULT_MINUTES_PER_QUESTION) * count
            for q_type, count in blueprint.type_mix.items()
        )
        basis = {
            q_type: QUESTION_MINUTES.get(q_type, DEFAULT_MINUTES_PER_QUESTION)
            for q_type in blueprint.type_mix
        }
    elif blueprint.total_questions:
        minutes = blueprint.total_questions * DEFAULT_MINUTES_PER_QUESTION
        basis = {"default": DEFAULT_MINUTES_PER_QUESTION}
    else:
        return None, {}
    return int(round(minutes)), basis


def plan_schedule(
    config: dict,
    blueprint: Optional[AssessmentBlueprint] = None,
    conflicts: tuple = (),
) -> SchedulePlan:
    """Pure scheduling analysis: the teacher's constraints, the duration the
    blueprint implies, and calendar collisions with the class's other exams."""
    duration = config.get("duration_minutes")
    start = _as_aware_utc(config.get("proposed_start"))
    end = _as_aware_utc(config.get("proposed_end"))
    estimated, basis = estimate_exam_duration(blueprint)
    window_minutes = (
        (end - start).total_seconds() / 60 if start and end and end > start else None
    )
    findings: list[Finding] = []

    # --- teacher constraints
    if start and end and end <= start:
        findings.append(
            Finding(
                severity="blocker",
                message="Proposed end must be after proposed start",
                stage=StageKey.SCHEDULING,
            )
        )
    if duration and window_minutes is not None and duration > window_minutes:
        findings.append(
            Finding(
                severity="blocker",
                message=f"Duration ({duration} min) exceeds the exam window ({window_minutes:.0f} min)",
                stage=StageKey.SCHEDULING,
            )
        )
    if not duration:
        findings.append(
            Finding(
                severity="warning",
                message="No duration set — the exam cannot be time-boxed yet",
                stage=StageKey.SCHEDULING,
            )
        )
    if not start or not end:
        findings.append(
            Finding(
                severity="warning",
                message="No exam window proposed — students cannot be told when to sit it",
                stage=StageKey.SCHEDULING,
            )
        )

    # --- duration analysis
    if duration and estimated:
        if duration < estimated * UNDER_DURATION_RATIO:
            findings.append(
                Finding(
                    severity="warning",
                    message=(
                        f"{duration} min may be tight — this question mix suggests about "
                        f"{estimated} min"
                    ),
                    stage=StageKey.SCHEDULING,
                )
            )
    elif estimated and not duration:
        findings.append(
            Finding(
                severity="info",
                message=f"This question mix suggests about {estimated} min",
                stage=StageKey.SCHEDULING,
            )
        )

    # --- academic calendar (the class's other exams)
    for conflict in conflicts:
        findings.append(
            Finding(
                severity="warning",
                message=(
                    f"Overlaps '{conflict.title}' already scheduled for this class"
                    + (
                        f" ({conflict.overlap_minutes:.0f} min overlap)"
                        if conflict.overlap_minutes
                        else ""
                    )
                ),
                stage=StageKey.SCHEDULING,
            )
        )

    return SchedulePlan(
        duration_minutes=duration,
        proposed_start=start,
        proposed_end=end,
        findings=findings,
        estimated_duration_minutes=estimated,
        duration_basis=basis,
        window_minutes=round(window_minutes, 1) if window_minutes is not None else None,
        conflicts=list(conflicts),
    )


def load_schedule_conflicts(
    class_id: UUID, start: Optional[datetime], end: Optional[datetime]
) -> tuple:
    """Other exams for this class whose window overlaps the proposed one.

    Examini has no institutional academic calendar (terms, holidays); the
    class's own exam schedule is the calendar signal the platform actually
    has. A real calendar can be added behind this same function."""
    if not start or not end:
        return ()
    from app.models.exam import Exam

    with db_session() as db:
        exams = (
            db.query(Exam)
            .filter(
                Exam.class_id == class_id,
                Exam.start_date.isnot(None),
                Exam.end_date.isnot(None),
                Exam.start_date < end,
                Exam.end_date > start,
            )
            .order_by(Exam.start_date)
            .limit(20)
            .all()
        )
        conflicts = []
        for exam in exams:
            exam_start = _as_aware_utc(exam.start_date)
            exam_end = _as_aware_utc(exam.end_date)
            overlap = None
            if exam_start and exam_end:
                latest_start = max(start, exam_start)
                earliest_end = min(end, exam_end)
                overlap = max((earliest_end - latest_start).total_seconds() / 60, 0.0)
            conflicts.append(
                ScheduleConflict(
                    exam_id=str(exam.id),
                    title=exam.title,
                    start_date=exam_start,
                    end_date=exam_end,
                    overlap_minutes=round(overlap, 1) if overlap is not None else None,
                    is_published=bool(exam.is_published),
                )
            )
        return tuple(conflicts)


def _schedule_inputs(ctx: StageContext) -> tuple:
    """Blueprint + calendar conflicts for the proposed window (sync I/O)."""
    blueprint_data = ctx.prior_artifacts.get(StageKey.ASSESSMENT_DESIGN.value)
    blueprint = AssessmentBlueprint(**blueprint_data) if blueprint_data else None
    conflicts = load_schedule_conflicts(
        ctx.class_id,
        _as_aware_utc(ctx.config.get("proposed_start")),
        _as_aware_utc(ctx.config.get("proposed_end")),
    )
    return blueprint, conflicts


class SchedulingHandler(StageHandler):
    """Scheduler — deterministic: constraint validation, duration estimation
    from the blueprint, and calendar collisions with the class's exams."""

    key = StageKey.SCHEDULING

    async def execute(self, ctx: StageContext) -> SchedulePlan:
        blueprint, conflicts = await asyncio.to_thread(_schedule_inputs, ctx)
        return plan_schedule(ctx.config, blueprint, conflicts)


# ============================================================ curriculum analyst (Phase 6)

def merge_outline(inventory: CurriculumOutline, analysis) -> CurriculumOutline:
    """Deterministic merge: the agent contributes ONLY the analytical half
    (topics/summary); the inventory facts (class, units, parseability,
    findings) are never model-authored."""
    return inventory.model_copy(
        update={"topics": list(analysis.topics), "summary": analysis.summary}
    )


def _extract_parseable_texts(ctx: StageContext, outline: CurriculumOutline) -> tuple[list, list]:
    """Extract text per parseable material, tolerating individual failures
    (a scanned PDF becomes a skipped entry, not a dead stage).
    Returns ([(material_id, title, text)], [skipped_titles])."""
    from app.services.material_service import MaterialService
    from app.services.parser_service import ParserService

    parseable_ids = [UUID(u.material_id) for u in outline.units if u.parseable]
    texts, skipped = [], []
    with db_session() as db:
        materials = MaterialService.get_materials_by_ids(db, parseable_ids, ctx.user_id)
        for material in materials:
            try:
                texts.append((str(material.id), material.title, ParserService.extract_text(material)))
            except ValueError:
                skipped.append(material.title)
    return texts, skipped


def mark_unreadable(outline: CurriculumOutline, texts: list) -> CurriculumOutline:
    """Correct `parseable` from what extraction actually produced.

    The inventory sets `parseable` from the FILE TYPE, which only says a format
    is text-bearing in principle — a scanned PDF is still a pdf. Once extraction
    has run we know the truth, and the artifact must reflect it: otherwise the
    UI shows a material badged 'Readable' directly above a blocker saying no
    text could be read from it."""
    extracted = {material_id for material_id, _, _ in texts}
    return outline.model_copy(
        update={
            "units": [
                unit
                if not unit.parseable or unit.material_id in extracted
                else unit.model_copy(update={"parseable": False})
                for unit in outline.units
            ]
        }
    )


class CurriculumAnalystHandler(StageHandler):
    """Agent-backed curriculum_analysis stage: deterministic inventory +
    Curriculum Analyst analysis, merged deterministically.

    Falls back to the inventory-only outline when there is nothing to
    analyze (blockers / no extractable text) — an agent run would waste
    tokens on a stage the reviewer must reject anyway. An agent failure
    fails the stage visibly (workflow FAILED) rather than silently
    degrading; the teacher re-runs after fixing the cause."""

    key = StageKey.CURRICULUM_ANALYSIS

    async def execute(self, ctx: StageContext) -> CurriculumOutline:
        inventory = await asyncio.to_thread(CurriculumAnalysisHandler._run, ctx)
        has_blockers = any(f.severity == "blocker" for f in inventory.findings)
        if has_blockers or not any(u.parseable for u in inventory.units):
            return inventory

        texts, skipped = await asyncio.to_thread(_extract_parseable_texts, ctx, inventory)
        # What the file type promised vs what the file actually yielded.
        inventory = mark_unreadable(inventory, texts)
        if not texts:
            # Every material looked parseable by file type but yielded no usable
            # text (typically image-only scans). This is a BLOCKER, not a quiet
            # inventory-only pass: without it the plan sails through review and
            # only fails at generation, where the cause is far less obvious.
            return inventory.model_copy(
                update={
                    "findings": [
                        *inventory.findings,
                        Finding(
                            severity="blocker",
                            message=(
                                "No text could be extracted from "
                                + (", ".join(f"'{title}'" for title in skipped) or "the selected materials")
                                + ". Scanned or image-only documents cannot be used to write "
                                "questions — upload a text-based file, or run OCR first."
                            ),
                            stage=StageKey.CURRICULUM_ANALYSIS,
                        ),
                    ]
                }
            )
        if skipped:
            inventory = inventory.model_copy(
                update={
                    "findings": [
                        *inventory.findings,
                        Finding(
                            severity="warning",
                            message=f"Text extraction failed for: {', '.join(skipped)}",
                            stage=StageKey.CURRICULUM_ANALYSIS,
                        ),
                    ]
                }
            )

        outcome = await self._run_agent(ctx, inventory, texts)
        ctx.run_id = outcome.run_id
        return merge_outline(inventory, outcome.final_output)

    @staticmethod
    async def _run_agent(ctx: StageContext, inventory: CurriculumOutline, texts: list):
        from app.ai.context import AIRunContext
        from app.ai.runtime.runner import execute_run

        material_ids = [material_id for material_id, _, _ in texts]
        run_context = AIRunContext(
            user_id=ctx.user_id,
            role=ctx.role,
            extra={
                # Context Engine hints (workflow + course facets) and the
                # guardrail's allowed-source list.
                "workflow_id": str(ctx.workflow_id),
                "stage": StageKey.CURRICULUM_ANALYSIS.value,
                "class_id": str(ctx.class_id),
                "material_ids": material_ids,
            },
        )
        parts = [
            f"Analyze the teaching materials of class '{inventory.class_name}'.",
        ]
        if ctx.rejection_notes:
            parts.append(f"Reviewer feedback from the previous revision: {ctx.rejection_notes}")
        parts.append(
            "Materials provided: "
            + ", ".join(f"{material_id} ('{title}')" for material_id, title, _ in texts)
        )
        for material_id, title, text in texts:
            parts.append(f"=== Material {material_id}: {title} ===\n{text}")
        return await execute_run(run_context, "curriculum_analyst", "\n\n".join(parts))


# ============================================================ assessment designer (Phase 7)

def merge_blueprint(skeleton: AssessmentBlueprint, design) -> AssessmentBlueprint:
    """Deterministic merge: the agent contributes ONLY the design half
    (topic allocations + rationale); the count skeleton (total, mixes,
    points) stays derived from the teacher's config. Aggregate mix
    contradictions are appended to validation_errors, which quality_review
    turns into blockers."""
    from app.ai.guardrails.output import design_consistency_errors

    return skeleton.model_copy(
        update={
            "topic_allocations": list(design.topic_allocations),
            "rationale": design.rationale,
            "validation_errors": [
                *skeleton.validation_errors,
                *design_consistency_errors(design, skeleton.type_mix),
            ],
        }
    )


class AssessmentDesignerHandler(StageHandler):
    """Agent-backed assessment_design stage: deterministic count skeleton +
    Assessment Designer allocation, merged deterministically.

    Falls back to the skeleton alone when there is nothing to design
    against — an invalid/empty question_config, or a curriculum outline with
    no topics (i.e. the deterministic curriculum handler produced only an
    inventory). An agent failure fails the stage visibly."""

    key = StageKey.ASSESSMENT_DESIGN

    async def execute(self, ctx: StageContext) -> AssessmentBlueprint:
        skeleton = normalize_blueprint(ctx.config.get("question_config") or {})
        if skeleton.validation_errors or skeleton.total_questions < 1:
            return skeleton
        # The teacher edited the numbers; recompute, do not re-narrate.
        if ctx.deterministic_only:
            return skeleton

        outline_data = ctx.prior_artifacts.get(StageKey.CURRICULUM_ANALYSIS.value)
        if not outline_data:
            return skeleton
        outline = CurriculumOutline(**outline_data)
        if not outline.topics:
            return skeleton

        outcome = await self._run_agent(ctx, outline, skeleton)
        ctx.run_id = outcome.run_id
        return merge_blueprint(skeleton, outcome.final_output)

    @staticmethod
    async def _run_agent(ctx: StageContext, outline: CurriculumOutline, skeleton: AssessmentBlueprint):
        import json

        from app.ai.context import AIRunContext
        from app.ai.runtime.runner import execute_run

        run_context = AIRunContext(
            user_id=ctx.user_id,
            role=ctx.role,
            extra={
                # Context Engine hints (workflow + course facets).
                "workflow_id": str(ctx.workflow_id),
                "stage": StageKey.ASSESSMENT_DESIGN.value,
                "class_id": str(ctx.class_id),
                # Guardrail inputs (never seen by the model).
                "topics": list(outline.topics),
                "total_questions": skeleton.total_questions,
            },
        )
        parts = [
            f"Design the assessment for class '{outline.class_name}'.",
            "Requested counts: "
            + json.dumps(
                {
                    "total": skeleton.total_questions,
                    "type_mix": skeleton.type_mix,
                    "difficulty_mix": skeleton.difficulty_mix,
                }
            ),
        ]
        if ctx.rejection_notes:
            parts.append(f"Reviewer feedback from the previous revision: {ctx.rejection_notes}")
        if outline.summary:
            parts.append(f"Curriculum summary: {outline.summary}")
        parts.append(
            "Curriculum topics:\n"
            + json.dumps([t.model_dump(mode="json") for t in outline.topics], indent=2)
        )
        return await execute_run(run_context, "assessment_designer", "\n\n".join(parts))


# ============================================================ quality reviewer (Phase 8)

def merge_quality_report(deterministic: QualityReport, review) -> QualityReport:
    """Deterministic merge with an ADD-ONLY blocker rule.

    The agent contributes per-dimension verdicts, observations, and a
    summary. Its observations can introduce blockers (failing a blueprint
    the structural checks let through) but can never clear one: `passed`
    stays `deterministic.passed AND no agent blocker`. A model cannot
    approve something the platform's own checks rejected."""
    agent_findings = [
        Finding(
            severity=observation.severity,
            message=f"[{observation.dimension.value}] {observation.message}",
            stage=StageKey.QUALITY_REVIEW,
        )
        for observation in review.observations
    ]
    return deterministic.model_copy(
        update={
            "findings": [*deterministic.findings, *agent_findings],
            "passed": deterministic.passed
            and not any(f.severity == "blocker" for f in agent_findings),
            "dimension_verdicts": list(review.dimension_verdicts),
            "summary": review.summary,
        }
    )


def _policy_facts(ctx: StageContext) -> dict:
    """Institution/academic policies for the review, sourced from the Context
    Engine's policy provider (derived from the platform's own grading
    function and settings — never re-declared here)."""
    from app.ai.context_engine.engine import ContextRequest
    from app.ai.context_engine.providers import AcademicPolicyProvider

    policies = AcademicPolicyProvider().collect(
        ContextRequest(user_id=ctx.user_id, role=ctx.role)
    )
    return {
        "pass_threshold_percent": policies.pass_threshold,
        "grade_bands": [
            {"min_percentage": b.min_percentage, "grade": b.grade} for b in policies.grade_bands
        ],
        "max_questions_per_exam": policies.max_questions_per_exam,
    }


class QualityReviewerHandler(StageHandler):
    """Agent-backed quality_review stage: deterministic structural checks +
    Quality Reviewer judgement, merged add-only.

    Falls back to the deterministic report when it already found blockers —
    the teacher must fix those before a nuanced review adds value."""

    key = StageKey.QUALITY_REVIEW

    async def execute(self, ctx: StageContext) -> QualityReport:
        outline_data = ctx.prior_artifacts.get(StageKey.CURRICULUM_ANALYSIS.value)
        blueprint_data = ctx.prior_artifacts.get(StageKey.ASSESSMENT_DESIGN.value)
        if not outline_data or not blueprint_data:
            raise ValidationError("Quality review requires the curriculum and design artifacts")
        outline = CurriculumOutline(**outline_data)
        blueprint = AssessmentBlueprint(**blueprint_data)

        deterministic = review_quality(outline, blueprint)
        if not deterministic.passed:
            return deterministic
        # The teacher edited the numbers; the structural verdict is what
        # changed, and a stale agent narrative alongside it would mislead.
        if ctx.deterministic_only:
            return deterministic

        outcome = await self._run_agent(ctx, outline, blueprint)
        ctx.run_id = outcome.run_id
        return merge_quality_report(deterministic, outcome.final_output)

    @staticmethod
    async def _run_agent(ctx: StageContext, outline: CurriculumOutline, blueprint: AssessmentBlueprint):
        import json

        from app.ai.context import AIRunContext
        from app.ai.runtime.runner import execute_run

        policies = await asyncio.to_thread(_policy_facts, ctx)
        run_context = AIRunContext(
            user_id=ctx.user_id,
            role=ctx.role,
            extra={
                # Context Engine hints (workflow + course facets).
                "workflow_id": str(ctx.workflow_id),
                "stage": StageKey.QUALITY_REVIEW.value,
                "class_id": str(ctx.class_id),
            },
        )
        parts = [
            f"Review the assessment blueprint for class '{outline.class_name}'.",
            "Institution academic policies: " + json.dumps(policies),
            "Assessment blueprint: " + json.dumps(blueprint.model_dump(mode="json"), indent=2),
        ]
        if ctx.rejection_notes:
            parts.append(f"Reviewer feedback from the previous revision: {ctx.rejection_notes}")
        if outline.summary:
            parts.append(f"Curriculum summary: {outline.summary}")
        if outline.topics:
            parts.append(
                "Curriculum topics:\n"
                + json.dumps([t.model_dump(mode="json") for t in outline.topics], indent=2)
            )
        else:
            parts.append(
                "No curriculum topic analysis is available — treat coverage and "
                "Bloom's taxonomy as not_assessable unless the blueprint itself "
                "provides the evidence."
            )
        return await execute_run(run_context, "quality_reviewer", "\n\n".join(parts))


# ============================================================ difficulty analyzer (Phase 9)

class DifficultyAnalysisMode:
    DETERMINISTIC = "deterministic"
    LLM = "llm"


def merge_difficulty_profile(profile: DifficultyProfile, analysis) -> DifficultyProfile:
    """Deterministic merge: the agent contributes ONLY interpretation
    (calibration, assessment, recommendations). Every number — distributions,
    indices, divergence, per-exam comparisons — stays as computed."""
    return profile.model_copy(
        update={
            "mode": DifficultyAnalysisMode.LLM,
            "calibration": analysis.calibration.value,
            "assessment": analysis.assessment,
            "recommendations": list(analysis.recommendations),
        }
    )


class DifficultyAnalyzerHandler(StageHandler):
    """Difficulty Analyzer — LLM mode.

    Runs the identical deterministic analysis first, then asks the agent to
    interpret those statistics. If the agent step is unavailable the profile
    is still complete: LLM mode strictly adds narrative on top of the
    deterministic numbers."""

    key = StageKey.DIFFICULTY_ANALYSIS

    async def execute(self, ctx: StageContext) -> DifficultyProfile:
        blueprint = AssessmentBlueprint(**ctx.prior_artifacts[StageKey.ASSESSMENT_DESIGN.value])
        history = await asyncio.to_thread(load_historical_difficulty, ctx.user_id)
        profile = build_difficulty_profile(blueprint, history)
        if not profile.target_distribution:
            return profile  # nothing to interpret — the blueprint has no difficulty mix
        if ctx.deterministic_only:
            return profile

        outcome = await self._run_agent(ctx, profile, bool(history.total))
        ctx.run_id = outcome.run_id
        return merge_difficulty_profile(profile, outcome.final_output)

    @staticmethod
    async def _run_agent(ctx: StageContext, profile: DifficultyProfile, has_history: bool):
        import json

        from app.ai.context import AIRunContext
        from app.ai.runtime.runner import execute_run

        run_context = AIRunContext(
            user_id=ctx.user_id,
            role=ctx.role,
            extra={
                # Context Engine hints (workflow + course facets).
                "workflow_id": str(ctx.workflow_id),
                "stage": StageKey.DIFFICULTY_ANALYSIS.value,
                "class_id": str(ctx.class_id),
                # Guardrail input (never seen by the model).
                "has_history": has_history,
            },
        )
        statistics = {
            "target_distribution": profile.target_distribution,
            "difficulty_index": profile.difficulty_index,
            "historical_distribution": profile.historical_distribution,
            "historical_difficulty_index": profile.historical_difficulty_index,
            "historical_question_count": profile.historical_question_count,
            "divergence": profile.divergence,
            "deterministic_notes": profile.notes,
        }
        parts = [
            "Interpret the difficulty statistics computed for this exam.",
            "Statistics: " + json.dumps(statistics, indent=2),
        ]
        if profile.exam_comparisons:
            parts.append(
                "Previous exams:\n"
                + json.dumps([c.model_dump(mode="json") for c in profile.exam_comparisons], indent=2)
            )
        else:
            parts.append(
                "No previous exams are available for comparison — the calibration "
                "must be 'uncertain'."
            )
        if ctx.rejection_notes:
            parts.append(f"Reviewer feedback from the previous revision: {ctx.rejection_notes}")
        return await execute_run(run_context, "difficulty_analyzer", "\n\n".join(parts))


# ============================================================ scheduler (Phase 10)

def merge_schedule_plan(plan: SchedulePlan, advice) -> SchedulePlan:
    """Deterministic merge: the agent contributes ONLY advice (readiness,
    rationale, recommendations, a suggested duration). The teacher's window
    and duration, the estimate, the window length and the conflicts are all
    left exactly as computed — and nothing here publishes anything."""
    return plan.model_copy(
        update={
            "readiness": advice.readiness.value,
            "rationale": advice.rationale,
            "recommendations": list(advice.recommendations),
            "recommended_duration_minutes": advice.recommended_duration_minutes,
        }
    )


class SchedulerHandler(StageHandler):
    """Agent-backed scheduling stage: the deterministic schedule analysis
    plus Scheduler judgement, merged deterministically.

    Falls back to the deterministic plan when the window is missing — there
    is nothing to assess, and the deterministic warning already says so."""

    key = StageKey.SCHEDULING

    async def execute(self, ctx: StageContext) -> SchedulePlan:
        blueprint, conflicts = await asyncio.to_thread(_schedule_inputs, ctx)
        plan = plan_schedule(ctx.config, blueprint, conflicts)
        if not plan.proposed_start or not plan.proposed_end:
            return plan
        if ctx.deterministic_only:
            return plan

        outcome = await self._run_agent(ctx, plan)
        ctx.run_id = outcome.run_id
        return merge_schedule_plan(plan, outcome.final_output)

    @staticmethod
    async def _run_agent(ctx: StageContext, plan: SchedulePlan):
        import json

        from app.ai.context import AIRunContext
        from app.ai.runtime.runner import execute_run

        run_context = AIRunContext(
            user_id=ctx.user_id,
            role=ctx.role,
            extra={
                # Context Engine hints (workflow + course facets).
                "workflow_id": str(ctx.workflow_id),
                "stage": StageKey.SCHEDULING.value,
                "class_id": str(ctx.class_id),
                # Guardrail input (never seen by the model).
                "has_window": bool(plan.proposed_start and plan.proposed_end),
            },
        )
        constraints = {
            "duration_minutes": plan.duration_minutes,
            "proposed_start": plan.proposed_start.isoformat() if plan.proposed_start else None,
            "proposed_end": plan.proposed_end.isoformat() if plan.proposed_end else None,
            "window_minutes": plan.window_minutes,
            "estimated_duration_minutes": plan.estimated_duration_minutes,
            "duration_basis_minutes_per_question": plan.duration_basis,
            "deterministic_findings": [f.message for f in plan.findings],
        }
        parts = [
            "Assess whether this exam can run as scheduled.",
            "Constraints and duration analysis: " + json.dumps(constraints, indent=2),
        ]
        if plan.conflicts:
            parts.append(
                "Exams already scheduled for this class in the same window:\n"
                + json.dumps([c.model_dump(mode="json") for c in plan.conflicts], indent=2)
            )
        else:
            parts.append("No other exams for this class overlap the proposed window.")
        if ctx.rejection_notes:
            parts.append(f"Reviewer feedback from the previous revision: {ctx.rejection_notes}")
        return await execute_run(run_context, "scheduler", "\n\n".join(parts))


def configure_scheduling_stage() -> None:
    """Flag-driven stage wiring: the Scheduler agent replaces the
    deterministic handler when AI_USE_SCHEDULER=true (and the AI layer is
    enabled). Re-invocable — tests toggle and re-configure."""
    from app.ai.config import ai_settings

    if ai_settings.enabled and ai_settings.use_scheduler:
        register(SchedulerHandler())
    else:
        register(SchedulingHandler())


def configure_difficulty_stage() -> None:
    """Mode-driven stage wiring (Phase 9 requires both modes to be
    supported): AI_DIFFICULTY_ANALYSIS_MODE=deterministic (default) computes
    the profile with no model; =llm adds agent interpretation on top of the
    same numbers. Re-invocable — tests toggle and re-configure."""
    from app.ai.config import ai_settings

    mode = (ai_settings.difficulty_analysis_mode or "").strip().lower()
    if ai_settings.enabled and mode == DifficultyAnalysisMode.LLM:
        register(DifficultyAnalyzerHandler())
    else:
        register(DifficultyAnalysisHandler())


def configure_quality_stage() -> None:
    """Flag-driven stage wiring: the Quality Reviewer agent replaces the
    deterministic handler when AI_USE_QUALITY_REVIEWER=true (and the AI layer
    is enabled). Re-invocable — tests toggle and re-configure."""
    from app.ai.config import ai_settings

    if ai_settings.enabled and ai_settings.use_quality_reviewer:
        register(QualityReviewerHandler())
    else:
        register(QualityReviewHandler())


def configure_design_stage() -> None:
    """Flag-driven stage wiring: the Assessment Designer agent replaces the
    deterministic handler when AI_USE_ASSESSMENT_DESIGNER=true (and the AI
    layer is enabled). Re-invocable — tests toggle and re-configure."""
    from app.ai.config import ai_settings

    if ai_settings.enabled and ai_settings.use_assessment_designer:
        register(AssessmentDesignerHandler())
    else:
        register(AssessmentDesignHandler())


def configure_curriculum_stage() -> None:
    """Flag-driven stage wiring: the Curriculum Analyst agent replaces the
    deterministic handler when AI_USE_CURRICULUM_ANALYST=true (and the AI
    layer is enabled). Re-invocable — tests toggle and re-configure."""
    from app.ai.config import ai_settings

    if ai_settings.enabled and ai_settings.use_curriculum_analyst:
        register(CurriculumAnalystHandler())
    else:
        register(CurriculumAnalysisHandler())


# ============================================================ agent adapter

class AgentStageHandler(StageHandler):
    """Adapter that lets a registered specialist agent execute a stage.

    Not registered by default — this is the seam future agents plug into:
        register(AgentStageHandler(StageKey.CURRICULUM_ANALYSIS, "curriculum_analyst"))
    The agent must be in the agent registry with a structured output of
    ARTIFACT_TYPES[stage_key]; the run is quota'd, budgeted, and recorded
    like every other run (it goes through runtime/runner.py)."""

    def __init__(self, stage_key: StageKey, agent_key: str):
        self.key = stage_key
        self.agent_key = agent_key

    async def execute(self, ctx: StageContext) -> BaseModel:
        import json

        from app.ai.context import AIRunContext
        from app.ai.runtime.runner import execute_run

        if ctx.deterministic_only:
            raise ValidationError(
                f"Stage '{self.key.value}' has no deterministic mode and cannot be "
                "recomputed from an adjusted question mix"
            )

        run_context = AIRunContext(
            user_id=ctx.user_id,
            role=ctx.role,
            extra={"workflow_id": str(ctx.workflow_id), "stage": self.key.value},
        )
        payload = json.dumps(
            {
                "config": ctx.config,
                "prior_artifacts": ctx.prior_artifacts,
                "revision": ctx.revision,
                "rejection_notes": ctx.rejection_notes,
            },
            default=str,
        )
        outcome = await execute_run(run_context, self.agent_key, payload)
        artifact_type = ARTIFACT_TYPES[self.key]
        if not isinstance(outcome.final_output, artifact_type):
            raise ValidationError(
                f"Agent '{self.agent_key}' did not produce a {artifact_type.__name__}"
            )
        return outcome.final_output


# ============================================================ registry

_HANDLERS: dict[StageKey, StageHandler] = {}


def register(handler: StageHandler) -> None:
    _HANDLERS[handler.key] = handler


def get_handler(stage_key: StageKey) -> StageHandler:
    handler = _HANDLERS.get(stage_key)
    if handler is None:
        raise ValidationError(f"No handler registered for stage '{stage_key.value}'")
    return handler


def registered_pipeline() -> tuple[StageKey, ...]:
    """The canonical pipeline, asserting every stage has a handler."""
    for stage in DEFAULT_PIPELINE:
        get_handler(stage)
    return DEFAULT_PIPELINE


# Default registrations. Every stage is configuration-driven: a deterministic
# handler by default, a specialist agent when its flag/mode is enabled
# (Phases 6-10).
configure_curriculum_stage()
configure_design_stage()
configure_quality_stage()
configure_difficulty_stage()
configure_scheduling_stage()
