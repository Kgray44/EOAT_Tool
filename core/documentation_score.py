from __future__ import annotations

from typing import Any

from .atlas_models import DocumentationStatus

CRITICAL_DOCUMENTATION_FIELDS = (
    "EOAT Assembly ID",
    "Tool #",
    "Press/Machine #",
    "EOAT Type",
    "Status",
    "Drawing/CAD Available?",
    "BOM Available?",
    "Process Binder Complete?",
)

IMPORTANT_DOCUMENTATION_FIELDS = (
    "Photos Taken?",
    "Photo Folder/Link",
    "Robot Type",
    "Robot Model/Controller",
    "Connection Type",
    "Sensors Present?",
    "Sensor Type",
    "Tubing Condition",
    "Tubing Routing Notes",
    "Quick Disconnects Present?",
    "Pneumatic Quick Disconnect Type",
    "Electrical Quick Disconnect Type",
    "Maintenance Frequency",
    "Spare Parts Identified?",
)

UNKNOWN_VALUES = {
    "",
    "n/a",
    "na",
    "none",
    "unknown",
    "unknown / not checked",
    "not checked",
    "select",
    "tbd",
    "todo",
}


def calculate_documentation_status(row: dict[str, Any], *, photo_count: int = 0) -> DocumentationStatus:
    present: list[str] = []
    missing: list[str] = []
    critical_missing: list[str] = []
    checklist: list[tuple[str, str]] = []

    for field_name in CRITICAL_DOCUMENTATION_FIELDS:
        ok = _has_meaningful_value(row.get(field_name))
        if field_name == "Photos Taken?" and photo_count:
            ok = True
        _record_field(field_name, ok, present, missing, critical_missing, checklist, critical=True)

    for field_name in IMPORTANT_DOCUMENTATION_FIELDS:
        ok = _has_meaningful_value(row.get(field_name))
        if field_name in {"Photos Taken?", "Photo Folder/Link"} and photo_count:
            ok = True
        _record_field(field_name, ok, present, missing, critical_missing, checklist, critical=False)

    total_weight = len(CRITICAL_DOCUMENTATION_FIELDS) * 2 + len(IMPORTANT_DOCUMENTATION_FIELDS)
    earned = sum(2 for field_name in CRITICAL_DOCUMENTATION_FIELDS if field_name in present)
    earned += sum(1 for field_name in IMPORTANT_DOCUMENTATION_FIELDS if field_name in present)
    score = round((earned / total_weight) * 100) if total_weight else 0
    if critical_missing:
        status = "Critical gaps" if score < 70 else "Missing important info"
    elif score >= 90:
        status = "Complete"
    elif score >= 75:
        status = "Mostly complete"
    elif score >= 50:
        status = "Missing important info"
    else:
        status = "Critical gaps"
    return DocumentationStatus(
        score=score,
        status_label=status,
        present_fields=tuple(present),
        missing_fields=tuple(missing),
        critical_missing_fields=tuple(critical_missing),
        checklist=tuple(checklist),
    )


def _record_field(
    field_name: str,
    ok: bool,
    present: list[str],
    missing: list[str],
    critical_missing: list[str],
    checklist: list[tuple[str, str]],
    *,
    critical: bool,
) -> None:
    if ok:
        if field_name not in present:
            present.append(field_name)
        checklist.append((field_name, "Present"))
        return
    if field_name not in missing:
        missing.append(field_name)
    if critical and field_name not in critical_missing:
        critical_missing.append(field_name)
    checklist.append((field_name, "Missing"))


def _has_meaningful_value(value: Any) -> bool:
    text = "" if value is None else str(value).strip()
    if not text:
        return False
    return text.casefold() not in UNKNOWN_VALUES


__all__ = [
    "CRITICAL_DOCUMENTATION_FIELDS",
    "IMPORTANT_DOCUMENTATION_FIELDS",
    "calculate_documentation_status",
]
