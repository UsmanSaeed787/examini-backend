"""Pure input validators (SDK-free; wrapped as SDK input guardrails in
agents/). Validates the previously-unvalidated question_config (audit §12/§15)
before any model call is made."""
from typing import List

from app.ai.config import ai_settings

_DIFFICULTY_KEYS = ("easy", "medium", "hard")
_TYPE_KEYS = ("mcq", "short_answer", "long_answer", "true_false")


def _as_count(value) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def validate_question_config(config: dict) -> List[str]:
    """Return a list of human-readable problems; empty list == valid."""
    errors: List[str] = []
    if not isinstance(config, dict) or not config:
        return ["question_config must be a non-empty object"]

    total = _as_count(config.get("total"))
    if total is None:
        errors.append("question_config.total must be a positive integer")
    elif not (1 <= total <= ai_settings.max_questions_per_exam):
        errors.append(
            f"question_config.total must be between 1 and {ai_settings.max_questions_per_exam}"
        )

    for group_name, keys in (("difficulty", _DIFFICULTY_KEYS), ("type", _TYPE_KEYS)):
        present = {k: config[k] for k in keys if k in config and config[k] is not None}
        if not present:
            continue
        counts = {}
        for key, raw in present.items():
            count = _as_count(raw)
            if count is None or count < 0:
                errors.append(f"question_config.{key} must be a non-negative integer")
            else:
                counts[key] = count
        if counts and total is not None and len(counts) == len(present):
            if sum(counts.values()) != total:
                errors.append(
                    f"question_config {group_name} counts must sum to total "
                    f"({sum(counts.values())} != {total})"
                )
    return errors


def validate_material_selection(material_count: int) -> List[str]:
    errors: List[str] = []
    if material_count < 1:
        errors.append("At least one material is required")
    if material_count > ai_settings.max_materials_per_run:
        errors.append(
            f"At most {ai_settings.max_materials_per_run} materials may be used per generation"
        )
    return errors
