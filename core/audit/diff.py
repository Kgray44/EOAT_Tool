from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from typing import Any

from core.audit.completion import UNKNOWN_NOT_CHECKED_VALUE
from core.audit_field_rules import is_na_value, normalize_text

CHANGE_ADDED = "added"
CHANGE_CHANGED = "changed"
CHANGE_CLEARED = "cleared"
CHANGE_SET_TO_NA = "set_to_na"
CHANGE_SMART_DEFAULTED = "smart_defaulted"
CHANGE_UNKNOWN_NOT_CHECKED = "unknown_not_checked"
CHANGE_UNCHANGED = "unchanged"

ROBOT_PNEUMATIC_FIELDS = (
    "Robot Vacuum Circuits",
    "Robot Pressure Circuits",
    "Robot Interchangeable Circuits",
)
ROBOT_INFO_FIELDS = (
    *ROBOT_PNEUMATIC_FIELDS,
    "Robot Notes",
)

COMPATIBILITY_IMPACT_FIELDS = (
    "Tool #",
    "Part Family",
    "Part Name/Description",
    "EOAT Type",
    "EOAT Moves",
    "Connection Type",
    "Number of Parts Picked",
    "# of Cups",
    "# of Grippers",
    "Sensor Type",
    "Sensor Brand/Model",
    "Tubing Condition",
    "Cable Management Condition",
)


@dataclass(frozen=True)
class AuditFieldChange:
    field: str
    before: str
    after: str
    change_type: str
    source: str = "audit"
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AuditSavePreview:
    audit_id: str
    changes: tuple[AuditFieldChange, ...]
    changed_fields: tuple[str, ...]
    cleared_fields: tuple[str, ...]
    set_to_na_fields: tuple[str, ...]
    smart_defaulted_fields: tuple[str, ...]
    unknown_not_checked_fields: tuple[str, ...]
    robot_info_changes: tuple[AuditFieldChange, ...]
    compatibility_impact_fields: tuple[str, ...]
    photo_warnings: tuple[str, ...]
    warnings: tuple[str, ...] = ()

    @property
    def has_changes(self) -> bool:
        return any(change.change_type != CHANGE_UNCHANGED for change in self.changes)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_audit_save_preview(
    before: Mapping[str, Any] | None,
    after: Mapping[str, Any],
    *,
    smart_defaulted_fields: Iterable[str] | None = None,
    robot_before: Mapping[str, Any] | None = None,
    compatibility_fields: Iterable[str] | None = None,
) -> AuditSavePreview:
    previous = _string_map(before or {})
    current = _string_map(after or {})
    robot_previous = _string_map(robot_before or {})
    smart_defaulted = {str(field) for field in smart_defaulted_fields or ()}
    fields = sorted(set(previous) | set(current), key=_field_sort_key)
    changes: list[AuditFieldChange] = []
    for field in fields:
        before_value = previous.get(field, "")
        after_value = current.get(field, "")
        change_type = _change_type(field, before_value, after_value, smart_defaulted)
        source = "robot_info" if field in ROBOT_INFO_FIELDS else "audit"
        changes.append(
            AuditFieldChange(
                field=field, before=before_value, after=after_value, change_type=change_type, source=source
            )
        )

    robot_changes = tuple(
        change for change in changes if change.field in ROBOT_INFO_FIELDS and change.change_type != CHANGE_UNCHANGED
    )
    for field in ROBOT_INFO_FIELDS:
        if field not in current and field in robot_previous:
            change = AuditFieldChange(
                field=field,
                before=robot_previous.get(field, ""),
                after="",
                change_type=CHANGE_UNCHANGED,
                source="robot_info",
                note="Robot_Info.xlsx value exists but the audit form did not include this field.",
            )
            robot_changes = (*robot_changes, change)

    changed = tuple(
        change.field
        for change in changes
        if change.change_type in {CHANGE_ADDED, CHANGE_CHANGED, CHANGE_SMART_DEFAULTED}
    )
    cleared = tuple(change.field for change in changes if change.change_type == CHANGE_CLEARED)
    set_to_na = tuple(change.field for change in changes if change.change_type == CHANGE_SET_TO_NA)
    unknowns = tuple(change.field for change in changes if change.change_type == CHANGE_UNKNOWN_NOT_CHECKED)
    compatibility_candidates = set(compatibility_fields or COMPATIBILITY_IMPACT_FIELDS)
    compatibility_impacts = tuple(
        change.field
        for change in changes
        if change.field in compatibility_candidates and change.change_type != CHANGE_UNCHANGED
    )
    photo_warnings = _photo_warnings(current)
    warnings = tuple(
        [
            *(f"Photo evidence: {warning}" for warning in photo_warnings),
            *(
                f"Robot info will update {change.field}."
                for change in robot_changes
                if change.change_type != CHANGE_UNCHANGED
            ),
        ]
    )
    return AuditSavePreview(
        audit_id=current.get("Audit ID", ""),
        changes=tuple(changes),
        changed_fields=changed,
        cleared_fields=cleared,
        set_to_na_fields=set_to_na,
        smart_defaulted_fields=tuple(field for field in changed if field in smart_defaulted),
        unknown_not_checked_fields=unknowns,
        robot_info_changes=robot_changes,
        compatibility_impact_fields=compatibility_impacts,
        photo_warnings=photo_warnings,
        warnings=warnings,
    )


def _change_type(field: str, before: str, after: str, smart_defaulted: set[str]) -> str:
    if before == after:
        return CHANGE_UNCHANGED
    if _is_unknown(after):
        return CHANGE_UNKNOWN_NOT_CHECKED
    if is_na_value(after):
        return CHANGE_SET_TO_NA
    if field in smart_defaulted:
        return CHANGE_SMART_DEFAULTED
    if not before and after:
        return CHANGE_ADDED
    if before and not after:
        return CHANGE_CLEARED
    return CHANGE_CHANGED


def _photo_warnings(entry: Mapping[str, str]) -> tuple[str, ...]:
    photos_taken = normalize_text(entry.get("Photos Taken?")).casefold()
    photo_link = normalize_text(entry.get("Photo Folder/Link"))
    warnings: list[str] = []
    if photos_taken == "no":
        warnings.append("Photos Taken? is No.")
    if photos_taken == "yes" and not photo_link:
        warnings.append("Photos are marked taken but no photo folder or link is recorded.")
    return tuple(warnings)


def _is_unknown(value: str) -> bool:
    return normalize_text(value).casefold() in {UNKNOWN_NOT_CHECKED_VALUE.casefold(), "unknown", "not checked"}


def _string_map(value: Mapping[str, Any]) -> dict[str, str]:
    return {str(key): normalize_text(item) for key, item in value.items()}


def _field_sort_key(field: str) -> tuple[int, str]:
    return (0 if field == "Audit ID" else 1, field.casefold())


__all__ = [
    "AuditFieldChange",
    "AuditSavePreview",
    "CHANGE_ADDED",
    "CHANGE_CHANGED",
    "CHANGE_CLEARED",
    "CHANGE_SET_TO_NA",
    "CHANGE_SMART_DEFAULTED",
    "CHANGE_UNKNOWN_NOT_CHECKED",
    "CHANGE_UNCHANGED",
    "ROBOT_INFO_FIELDS",
    "ROBOT_PNEUMATIC_FIELDS",
    "build_audit_save_preview",
]
