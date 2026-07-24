"""Stable presentation models.  Deployment policy stays in :mod:`deployment`."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class GuiStatus(StrEnum):
    PASS = "PASS"
    WARNING = "WARNING"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"
    NOT_RUN = "NOT RUN"


def map_status(value: object, *, has_blockers: bool = False, has_warnings: bool = False) -> GuiStatus:
    """Map engine vocabulary without converting skipped or unknown work into success."""

    text = str(value or "").upper().replace("_", " ")
    if has_blockers or "BLOCK" in text or "NOT READY" in text:
        return GuiStatus.BLOCKED
    if any(token in text for token in ("FAIL", "ERROR", "INVALID", "DENIED")):
        return GuiStatus.FAILED
    if any(token in text for token in ("NOT RUN", "SKIP", "NOT APPLICABLE")):
        return GuiStatus.NOT_RUN
    if not text or "UNKNOWN" in text or "UNAVAILABLE" in text or "NOT INSPECTED" in text:
        return GuiStatus.UNKNOWN
    if has_warnings or "WARN" in text:
        return GuiStatus.WARNING
    if any(token in text for token in ("PASS", "READY", "VALID", "VERIFIED", "SUCCEEDED", "AVAILABLE")):
        return GuiStatus.PASS
    return GuiStatus.UNKNOWN


@dataclass(frozen=True)
class OperationResult:
    tool: str
    operation: str
    status: GuiStatus
    summary: str
    details: dict[str, Any] = field(default_factory=dict)
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    started_at_utc: str | None = None
    ended_at_utc: str | None = None
    receipt_path: str | None = None


DANGEROUS_PHASE_ONE_ACTIONS = frozenset(
    {
        "version bump",
        "commit",
        "tag",
        "push",
        "publication",
        "github release creation",
        "upload",
        "stage",
        "activate",
        "migration",
        "rollback",
        "abort",
        "recovery mutation",
        "helper installation",
        "host configuration",
        "service restart",
        "symlink change",
        "token rotation",
    }
)
