from __future__ import annotations

from typing import Literal

COMPATIBLE_STATUS_CODES = frozenset({"compatible", "verified_compatible", "approved"})
INCOMPATIBLE_STATUS_CODES = frozenset({"incompatible", "failed", "not_compatible"})
REVIEW_STATUS_CODES = frozenset({"needs_review", "review_required"})

PairResult = Literal["COMPATIBLE", "INCOMPATIBLE", "NEEDS_REVIEW", "UNKNOWN", "NOT_EVALUATED"]


def classify_status(code: str | None) -> PairResult:
    """Fail closed: only explicitly approved status codes are compatible."""
    normalized = (code or "").strip().casefold()
    if normalized in COMPATIBLE_STATUS_CODES:
        return "COMPATIBLE"
    if normalized in INCOMPATIBLE_STATUS_CODES:
        return "INCOMPATIBLE"
    if normalized in REVIEW_STATUS_CODES:
        return "NEEDS_REVIEW"
    return "UNKNOWN"
