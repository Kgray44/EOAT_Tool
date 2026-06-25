from __future__ import annotations

from enum import Enum

from .atlas_models import EOATRecord, MachineRecord, ToolRecord, WarningItem


class RelationshipHealth(str, Enum):
    VERIFIED = "VERIFIED"
    REVIEW = "REVIEW"
    MISSING = "MISSING"
    INVALID = "INVALID"
    UNKNOWN = "UNKNOWN"


HEALTH_LABELS = {
    RelationshipHealth.VERIFIED: "Verified",
    RelationshipHealth.REVIEW: "Review",
    RelationshipHealth.MISSING: "Missing",
    RelationshipHealth.INVALID: "Invalid",
    RelationshipHealth.UNKNOWN: "Unknown",
}

HEALTH_BADGE_KINDS = {
    RelationshipHealth.VERIFIED: "verified",
    RelationshipHealth.REVIEW: "review",
    RelationshipHealth.MISSING: "missing",
    RelationshipHealth.INVALID: "invalid",
    RelationshipHealth.UNKNOWN: "unknown",
}


def health_label(health: RelationshipHealth | str) -> str:
    return HEALTH_LABELS.get(_health_value(health), "Unknown")


def health_badge_kind(health: RelationshipHealth | str) -> str:
    return HEALTH_BADGE_KINDS.get(_health_value(health), "unknown")


def eoat_relationship_health(eoat: EOATRecord | None) -> RelationshipHealth:
    if eoat is None:
        return RelationshipHealth.UNKNOWN
    if not eoat.eoat_id:
        return RelationshipHealth.UNKNOWN
    if not eoat.tools or not eoat.machines:
        return RelationshipHealth.MISSING
    if eoat.documentation.score < 50:
        return RelationshipHealth.REVIEW
    if eoat.photo_count <= 0:
        return RelationshipHealth.REVIEW
    if eoat.photos.missing_categories:
        return RelationshipHealth.REVIEW
    if _has_severe_warning(eoat.warnings):
        return RelationshipHealth.REVIEW
    return RelationshipHealth.VERIFIED


def machine_relationship_health(machine: MachineRecord | None) -> RelationshipHealth:
    if machine is None:
        return RelationshipHealth.UNKNOWN
    if not machine.machine:
        return RelationshipHealth.UNKNOWN
    if machine.compatible_tools and not machine.compatible_eoats:
        return RelationshipHealth.MISSING
    if not machine.compatible_tools and not machine.compatible_eoats:
        return RelationshipHealth.MISSING
    if machine.documentation_score < 50 or _has_severe_warning(machine.warnings):
        return RelationshipHealth.REVIEW
    return RelationshipHealth.VERIFIED


def tool_relationship_health(tool: ToolRecord | None) -> RelationshipHealth:
    if tool is None:
        return RelationshipHealth.UNKNOWN
    if not tool.tool:
        return RelationshipHealth.UNKNOWN
    if not tool.compatible_eoats:
        return RelationshipHealth.MISSING
    if not tool.compatible_machines:
        return RelationshipHealth.REVIEW
    if _has_severe_warning(tool.warnings):
        return RelationshipHealth.REVIEW
    return RelationshipHealth.VERIFIED


def validation_relationship_health(status: str, *, manual_override: bool = False) -> RelationshipHealth:
    folded = str(status or "").casefold()
    if manual_override or "manual override" in folded:
        return RelationshipHealth.REVIEW
    if "confirmed" in folded and "not" not in folded and "partial" not in folded:
        return RelationshipHealth.VERIFIED
    if "partial" in folded or "missing" in folded:
        return RelationshipHealth.REVIEW
    if "not confirmed" in folded or "invalid" in folded:
        return RelationshipHealth.INVALID
    return RelationshipHealth.UNKNOWN


def _health_value(health: RelationshipHealth | str) -> RelationshipHealth:
    if isinstance(health, RelationshipHealth):
        return health
    text = str(health).split(".")[-1].upper()
    try:
        return RelationshipHealth(text)
    except ValueError:
        return RelationshipHealth.UNKNOWN


def _has_severe_warning(warnings: tuple[WarningItem, ...]) -> bool:
    for warning in warnings:
        text = f"{warning.severity} {warning.title}".casefold()
        if any(token in text for token in ("critical", "error", "invalid", "unsafe")):
            return True
    return False


__all__ = [
    "HEALTH_BADGE_KINDS",
    "HEALTH_LABELS",
    "RelationshipHealth",
    "eoat_relationship_health",
    "health_badge_kind",
    "health_label",
    "machine_relationship_health",
    "tool_relationship_health",
    "validation_relationship_health",
]
