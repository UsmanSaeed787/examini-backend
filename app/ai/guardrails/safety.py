"""Role-appropriateness checks on final conversational output.

Deliberately minimal in v1: assistant agents only hold read-scoped tools, so
the primary defense is the authz matrix. This module exists as the seam for
richer checks (PII redaction, answer-key leak detection) without touching
agents or runtime."""
from typing import List

MAX_OUTPUT_CHARS = 20_000


def validate_assistant_reply(text: str) -> List[str]:
    errors: List[str] = []
    if text and len(text) > MAX_OUTPUT_CHARS:
        errors.append("Reply exceeds the maximum allowed length")
    return errors
