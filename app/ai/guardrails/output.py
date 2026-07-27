"""Pure output validators (SDK-free; wrapped as SDK output guardrails in
agents/). Verifies the model actually honored the request — counts, option
integrity — none of which the legacy path checked (audit §12)."""
from collections import Counter
from typing import Iterable, List

from app.ai.guardrails.input import _as_count
from app.ai.schemas.outputs import (
    AssessmentDesignOutput,
    CurriculumAnalysisOutput,
    DifficultyAnalysisOutput,
    DifficultyCalibration,
    GeneratedExamOutput,
    QualityDimension,
    QualityReviewOutput,
    ScheduleReadiness,
    SchedulePlanOutput,
    TopicAnalysis,
)
from app.utils.constants import QuestionType

_QUESTION_TYPES = {t.value for t in QuestionType}


def validate_generated_exam(output: GeneratedExamOutput, config: dict) -> List[str]:
    """Return a list of human-readable problems; empty list == valid."""
    errors: List[str] = []
    questions = output.questions or []
    if not questions:
        return ["The generated exam contains no questions"]

    total = _as_count(config.get("total")) if isinstance(config, dict) else None
    if total is not None and len(questions) != total:
        errors.append(f"Expected {total} questions, got {len(questions)}")

    type_counts: Counter = Counter()
    difficulty_counts: Counter = Counter()

    for idx, q in enumerate(questions, 1):
        type_counts[q.question_type.value] += 1
        difficulty_counts[q.difficulty_level.value] += 1

        if q.question_type in (QuestionType.MCQ, QuestionType.TRUE_FALSE):
            options = q.options or []
            correct = sum(1 for o in options if o.is_correct)
            if q.question_type == QuestionType.MCQ:
                if len(options) < 2:
                    errors.append(f"Question {idx}: MCQ must have at least 2 options")
                if correct < 1:
                    errors.append(f"Question {idx}: MCQ must have at least one correct option")
            else:  # TRUE_FALSE
                if len(options) != 2:
                    errors.append(f"Question {idx}: true/false must have exactly 2 options")
                if correct != 1:
                    errors.append(f"Question {idx}: true/false must have exactly one correct option")

    if isinstance(config, dict):
        for key in ("mcq", "short_answer", "long_answer", "true_false"):
            expected = _as_count(config.get(key))
            if expected is not None and type_counts.get(key, 0) != expected:
                errors.append(f"Expected {expected} '{key}' questions, got {type_counts.get(key, 0)}")
        for key in ("easy", "medium", "hard"):
            expected = _as_count(config.get(key))
            if expected is not None and difficulty_counts.get(key, 0) != expected:
                errors.append(
                    f"Expected {expected} '{key}' questions, got {difficulty_counts.get(key, 0)}"
                )
    return errors


def blueprint_question_config(blueprint) -> dict:
    """Project an approved AssessmentBlueprint back onto the question_config
    shape the generator's guardrails already speak.

    The blueprint's count skeleton is never model-authored (it is derived
    from the teacher's config in normalize_blueprint), so this keeps
    materialization driven by what the teacher actually approved rather than
    by the raw request — after rejections and config_patch corrections the
    two can differ."""
    config: dict = {"total": blueprint.total_questions}
    config.update({k: v for k, v in (blueprint.type_mix or {}).items()})
    config.update({k: v for k, v in (blueprint.difficulty_mix or {}).items()})
    return config


def validate_generated_against_blueprint(
    output: GeneratedExamOutput, blueprint
) -> List[str]:
    """Post-generation quality validation: do the produced questions honor
    the blueprint the teacher approved?

    Layered on top of validate_generated_exam (counts, mixes, option
    integrity) with the checks only a blueprint makes possible — that each
    topic received the number of questions it was allocated. Topic checks are
    skipped when the design carries no allocations or the model tagged no
    topics: an unverifiable dimension is reported as nothing, never as a
    pass (same honesty rule as the quality reviewer's 'not_assessable')."""
    errors = validate_generated_exam(output, blueprint_question_config(blueprint))

    allocations = getattr(blueprint, "topic_allocations", None) or []
    if not allocations:
        return errors
    tagged = [q for q in (output.questions or []) if q.topic]
    if not tagged:
        return errors

    actual: Counter = Counter(q.topic.strip() for q in tagged)
    expected = {a.topic_title: a.question_count for a in allocations}
    for title, count in expected.items():
        produced = actual.get(title, 0)
        if produced != count:
            errors.append(
                f"Topic '{title}': blueprint allocates {count} question(s), "
                f"generated {produced}"
            )
    unknown = sorted(set(actual) - set(expected))
    if unknown:
        errors.append(f"Questions tagged with topic(s) outside the blueprint: {unknown}")
    return errors


def validate_curriculum_analysis(
    output: CurriculumAnalysisOutput, allowed_material_ids: Iterable[str]
) -> List[str]:
    """Curriculum Analyst output checks: analysis must be non-empty, every
    topic needs at least one learning outcome and one Bloom level, and cited
    source materials must be among the materials actually provided (the
    model cannot invent sources). Bloom vocabulary itself is enforced by the
    BloomLevel enum at schema level."""
    errors: List[str] = []
    if not output.topics:
        return ["The analysis contains no topics"]
    allowed = {str(m) for m in allowed_material_ids}
    for idx, topic in enumerate(output.topics, 1):
        if not topic.learning_outcomes:
            errors.append(f"Topic {idx} ('{topic.title}'): no learning outcomes identified")
        if not topic.bloom_levels:
            errors.append(f"Topic {idx} ('{topic.title}'): no Bloom's taxonomy levels estimated")
        unknown = [m for m in topic.source_material_ids if m not in allowed]
        if unknown:
            errors.append(
                f"Topic {idx} ('{topic.title}'): cites unknown material id(s) {unknown}"
            )
    return errors


def validate_assessment_design(
    output: AssessmentDesignOutput,
    topics: Iterable[TopicAnalysis],
    total_questions: int,
) -> List[str]:
    """Assessment Designer STRUCTURAL checks (guardrail tripwires).

    The designer allocates questions across the curriculum's topics: it may
    not invent topics, may not exceed the cognitive levels the curriculum
    supports, and its allocation must add up to the requested total. Mix
    consistency against the teacher's global type_mix is a cross-artifact
    concern reported separately (see design_consistency_errors)."""
    errors: List[str] = []
    if not output.topic_allocations:
        return ["The design contains no topic allocations"]

    known = {t.title: t for t in topics}
    seen: set[str] = set()
    for idx, allocation in enumerate(output.topic_allocations, 1):
        label = f"Allocation {idx} ('{allocation.topic_title}')"
        topic = known.get(allocation.topic_title)
        if topic is None:
            errors.append(f"{label}: not a topic from the curriculum outline")
            continue
        if allocation.topic_title in seen:
            errors.append(f"{label}: duplicated allocation for the same topic")
        seen.add(allocation.topic_title)

        bad_types = [t for t in allocation.question_types if t not in _QUESTION_TYPES]
        if bad_types:
            errors.append(f"{label}: unknown question type(s) {bad_types}")
        elif allocation.question_types:
            per_type_total = sum(allocation.question_types.values())
            if per_type_total != allocation.question_count:
                errors.append(
                    f"{label}: per-type counts sum to {per_type_total}, "
                    f"expected {allocation.question_count}"
                )
        if topic.bloom_levels:
            unsupported = [b.value for b in allocation.bloom_levels if b not in topic.bloom_levels]
            if unsupported:
                errors.append(
                    f"{label}: Bloom level(s) {unsupported} exceed what the curriculum "
                    "analysis found for this topic"
                )

    allocated = sum(a.question_count for a in output.topic_allocations)
    if total_questions and allocated != total_questions:
        errors.append(
            f"Allocations sum to {allocated} questions, expected {total_questions}"
        )
    return errors


def validate_quality_review(output: QualityReviewOutput) -> List[str]:
    """Quality Reviewer structural checks (guardrail tripwires).

    The review must actually cover every required dimension exactly once,
    and a negative verdict must be substantiated by at least one observation
    on that dimension — no unexplained failures, and no silently skipped
    checks."""
    errors: List[str] = []
    if not output.dimension_verdicts:
        return ["The review contains no dimension verdicts"]

    seen = Counter(v.dimension for v in output.dimension_verdicts)
    missing = [d.value for d in QualityDimension if seen.get(d, 0) == 0]
    if missing:
        errors.append(f"Review does not cover required dimension(s): {missing}")
    duplicated = [d.value for d, count in seen.items() if count > 1]
    if duplicated:
        errors.append(f"Review gives more than one verdict for dimension(s): {duplicated}")

    observed = {o.dimension for o in output.observations}
    for verdict in output.dimension_verdicts:
        if verdict.verdict in ("fail", "concerns") and verdict.dimension not in observed:
            errors.append(
                f"Dimension '{verdict.dimension.value}' is marked '{verdict.verdict}' "
                "but has no supporting observation"
            )
    return errors


def validate_difficulty_analysis(
    output: DifficultyAnalysisOutput, has_history: bool
) -> List[str]:
    """Difficulty Analyzer structural checks (guardrail tripwires).

    Two honesty rules: a comparison cannot be claimed when there is no
    history to compare against, and a non-aligned calibration must come with
    at least one actionable recommendation."""
    errors: List[str] = []
    if not has_history and output.calibration != DifficultyCalibration.UNCERTAIN:
        errors.append(
            f"Calibration '{output.calibration.value}' claims a comparison, but there are "
            "no previous exams to compare against (expected 'uncertain')"
        )
    if output.calibration in (DifficultyCalibration.EASIER, DifficultyCalibration.HARDER) and not output.recommendations:
        errors.append(
            f"Calibration '{output.calibration.value}' has no recommendation for the teacher"
        )
    return errors


def validate_schedule_plan(output: SchedulePlanOutput, has_window: bool) -> List[str]:
    """Scheduler structural checks (guardrail tripwires).

    Honesty rules mirroring the other analysts: no readiness verdict can be
    claimed without a proposed window, and any non-ready verdict must come
    with something the teacher can act on."""
    errors: List[str] = []
    if not has_window and output.readiness != ScheduleReadiness.INSUFFICIENT_INFORMATION:
        errors.append(
            f"Readiness '{output.readiness.value}' assumes a schedule, but no exam window "
            "was proposed (expected 'insufficient_information')"
        )
    if has_window and output.readiness == ScheduleReadiness.INSUFFICIENT_INFORMATION:
        errors.append(
            "Readiness 'insufficient_information' contradicts the proposed exam window"
        )
    if (
        output.readiness in (ScheduleReadiness.ADJUST, ScheduleReadiness.BLOCKED)
        and not output.recommendations
    ):
        errors.append(
            f"Readiness '{output.readiness.value}' has no recommendation for the teacher"
        )
    return errors


def design_consistency_errors(
    output: AssessmentDesignOutput, type_mix: dict
) -> List[str]:
    """Cross-artifact check: when every allocation declares per-type counts,
    their aggregate must match the teacher's requested type mix. Reported as
    blueprint validation_errors (quality_review turns them into blockers)
    rather than a tripwire — the design is structurally valid, it just
    contradicts the request."""
    if not type_mix or not output.topic_allocations:
        return []
    if not all(a.question_types for a in output.topic_allocations):
        return []
    aggregate: Counter = Counter()
    for allocation in output.topic_allocations:
        aggregate.update(allocation.question_types)
    errors: List[str] = []
    for q_type, expected in type_mix.items():
        actual = aggregate.get(q_type, 0)
        if actual != expected:
            errors.append(
                f"Design allocates {actual} '{q_type}' question(s), the requested mix asks for {expected}"
            )
    return errors
