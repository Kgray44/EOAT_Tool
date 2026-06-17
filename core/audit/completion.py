from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from typing import Any

from core.audit.schema import AuditFieldSpec, all_audit_fields, audit_sections, field_by_header
from core.audit_constants import (
    AUDIT_CONTEXT_COMPATIBILITY,
    AUDIT_CONTEXT_FIELD,
    AUDIT_CONTEXT_INSTALLED,
    COMPATIBILITY_CONFIDENCE_FIELD,
    COMPATIBILITY_SOURCE_FIELD,
    CYLINDER_FIELDS,
    ENTRY_TYPE_COMPATIBLE,
    ENTRY_TYPE_FIELD,
    IGNORED_EMPTY_FIELDS_AT_OVERRIDE_FIELD,
    MANUAL_COMPLETION_OVERRIDE_FIELD,
    MANUAL_COMPLETION_OVERRIDE_TIMESTAMP_FIELD,
    MANUAL_COMPLETION_OVERRIDE_USER_FIELD,
    PHYSICAL_AUDIT_VERIFIED_FIELD,
    SOURCE_AUDIT_ID_FIELD,
)
from core.audit_context import INSTALLATION_ONLY_FIELDS, infer_audit_context
from core.audit_field_rules import (
    cylinder_optional_reason,
    cylinder_section_in_use,
    entry_type_requirements,
    field_applies,
    field_group,
    hybrid_completeness_warnings,
    ignored_empty_fields_at_override,
    is_meaningful_value,
    is_na_value,
    manual_completion_override_enabled,
    non_applicable_reason,
    normalize_cylinder_fields,
    normalize_text,
    semantic_consistency_warnings,
)
from core.audit_scores import calculate_split_scores
from core.gripper_fields import CUP_COUNT_FIELD
from core.tool_fields import TOOL_FIELD

STATE_VERIFIED_COMPLETE = "verified_complete"
STATE_MISSING = "missing"
STATE_UNKNOWN_NOT_CHECKED = "unknown_not_checked"
STATE_NOT_APPLICABLE = "not_applicable"
STATE_FOLLOW_UP_NEEDED = "follow_up_needed"
STATE_NOT_OBSERVABLE = "not_observable"
STATE_STALE_CONFLICT = "stale_conflict"
STATE_EXCLUDED = "excluded"
STATE_IGNORED_BY_OPTIONAL_GROUP = "ignored_by_optional_group"
STATE_IGNORED_BY_MANUAL_OVERRIDE = "ignored_by_manual_override"

UNKNOWN_NOT_CHECKED_VALUE = "Unknown / Not Checked"
UNKNOWN_VALUES = {"unknown / not checked", "unknown", "not checked"}

ACTIONABLE_STATES = {
    STATE_MISSING,
    STATE_UNKNOWN_NOT_CHECKED,
    STATE_FOLLOW_UP_NEEDED,
    STATE_STALE_CONFLICT,
}
NON_COUNTING_STATES = {
    STATE_NOT_APPLICABLE,
    STATE_NOT_OBSERVABLE,
    STATE_EXCLUDED,
    STATE_IGNORED_BY_OPTIONAL_GROUP,
    STATE_IGNORED_BY_MANUAL_OVERRIDE,
}

DEFAULT_EXCLUDED_FIELDS = frozenset(
    {
        "Tubing Routing Notes",
        "Robot Notes",
        "Notes",
        "Final Notes",
        SOURCE_AUDIT_ID_FIELD,
        COMPATIBILITY_SOURCE_FIELD,
        PHYSICAL_AUDIT_VERIFIED_FIELD,
        COMPATIBILITY_CONFIDENCE_FIELD,
        MANUAL_COMPLETION_OVERRIDE_FIELD,
        MANUAL_COMPLETION_OVERRIDE_TIMESTAMP_FIELD,
        MANUAL_COMPLETION_OVERRIDE_USER_FIELD,
        IGNORED_EMPTY_FIELDS_AT_OVERRIDE_FIELD,
    }
)

IDENTITY_FIELDS = {"Audit ID", "Audit Date", "Auditor", "Plant/Area", "Press/Machine #", AUDIT_CONTEXT_FIELD, "Status"}
COMPATIBILITY_COMPLETION_FIELDS = {"Audit ID", ENTRY_TYPE_FIELD, "Press/Machine #", TOOL_FIELD}
VISIBILITY_CONTROLLER_FIELDS = {
    "EOAT Type",
    "Sensors Present?",
    "Electrical/Wiring Present?",
    "Quick Disconnects Present?",
}
EOAT_TOOLING_FIELDS = {
    TOOL_FIELD,
    "Part Family",
    "Part Name/Description",
    "EOAT Type",
    "EOAT Moves",
    "Connection Type",
    "Number of Parts Picked",
    CUP_COUNT_FIELD,
    "# of Grippers",
    "Gripper Type",
    "Gripper Model",
    "# of Cylinders",
    "Cylinder Type",
    "Cup Type/Material",
    "Cup Diameter/Size",
    "Vacuum Generator Type",
    "Estimated EOAT Weight",
}
MAJOR_ENGINEERING_FIELDS = {
    "Robot Type",
    "Robot Model/Controller",
    "Cleanroom/Non-Cleanroom",
    "Tubing Condition",
    "Mounting Hardware Condition",
    "EOAT Alignment Condition",
    "Fastener/Locking Hardware Present?",
    "Known Issues",
    "Drop/Mis-Pick History",
    "Maintenance Frequency",
    "Cycle Time Concern?",
    "Scrap/Quality Concern?",
    "Changeover Difficulty",
    "Priority",
    "Pilot Candidate?",
}
SENSOR_PNEUMATIC_ELECTRICAL_GROUPS = {
    "sensor",
    "electrical",
    "pneumatic",
    "pneumatic_circuit",
    "routing",
    "quick_disconnect",
}
DOCUMENTATION_GROUPS = {"documentation", "photo"}


@dataclass(frozen=True)
class FieldCompletionStatus:
    field: str
    state: str
    value: str
    section: str = ""
    group: str = ""
    field_id: str = ""
    workbook_header: str = ""
    applies: bool = True
    counted: bool = True
    verified: bool = False
    required: bool = False
    important: bool = False
    reason: str = ""
    priority: int = 7
    original_state: str = ""

    @property
    def truth_state(self) -> str:
        return self.original_state or self.state

    @property
    def is_actionable(self) -> bool:
        return self.state in ACTIONABLE_STATES

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SectionCompletionStatus:
    name: str
    counted_field_count: int
    verified_complete_count: int
    missing_count: int
    unknown_not_checked_count: int
    not_applicable_count: int
    follow_up_needed_count: int
    not_observable_count: int
    stale_conflict_count: int
    excluded_count: int
    ignored_by_optional_group_count: int
    ignored_by_manual_override_count: int
    percent_complete: int
    fields: tuple[FieldCompletionStatus, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AuditCompletionSummary:
    audit_id: str
    entry_type: str
    audit_context: str
    mode: str
    percent_complete: int
    raw_percent_complete: int
    eoat_documentation_score: int
    installation_readiness_score: int
    installed_cell_validation_score: int | str
    can_finish: bool
    manual_completion_override: bool
    manual_completion_override_applied: bool
    manual_completion_override_timestamp: str
    manual_completion_override_user: str
    ignored_empty_fields_at_override: tuple[str, ...]
    applicable_field_count: int
    counted_field_count: int
    verified_complete_count: int
    missing_fields: tuple[str, ...]
    truth_missing_fields: tuple[str, ...]
    unknown_not_checked_fields: tuple[str, ...]
    not_applicable_fields: tuple[FieldCompletionStatus, ...]
    follow_up_fields: tuple[str, ...]
    not_observable_fields: tuple[str, ...]
    stale_conflict_fields: tuple[str, ...]
    excluded_fields: tuple[str, ...]
    ignored_by_optional_group_fields: tuple[str, ...]
    ignored_by_manual_override_fields: tuple[str, ...]
    missing_required_fields: tuple[str, ...]
    missing_important_fields: tuple[str, ...]
    guided_fields: tuple[str, ...]
    next_best_field: str
    next_best_reason: str
    sections: tuple[SectionCompletionStatus, ...]
    findings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def calculate_audit_completion(
    entry: Mapping[str, Any],
    sections: Mapping[str, list[str] | tuple[str, ...]] | None = None,
    *,
    excluded_fields: set[str] | frozenset[str] | tuple[str, ...] | None = None,
    allow_manual_override: bool = True,
    mode: str = "",
) -> AuditCompletionSummary:
    current_entry = normalize_cylinder_fields({str(key): normalize_text(value) for key, value in entry.items()})
    section_map = sections or audit_sections()
    excluded = set(DEFAULT_EXCLUDED_FIELDS if excluded_fields is None else excluded_fields)
    audit_context = infer_audit_context(current_entry)
    requirements = entry_type_requirements(current_entry)
    entry_type = (
        ENTRY_TYPE_COMPATIBLE
        if audit_context == AUDIT_CONTEXT_COMPATIBILITY
        else str(requirements.get("entry_type", ""))
    )
    required_fields = set(requirements.get("required", ()))
    important_fields = set(requirements.get("important", ()))
    if entry_type.casefold() != ENTRY_TYPE_COMPATIBLE.casefold():
        required_fields.update(
            field
            for field in IDENTITY_FIELDS
            if field not in excluded and (field in current_entry or field in _section_fields(section_map))
        )

    raw_section_statuses: list[SectionCompletionStatus] = []
    raw_statuses: list[FieldCompletionStatus] = []
    for section_name, fields in section_map.items():
        field_statuses = tuple(
            classify_completion_field(
                current_entry,
                field,
                section=str(section_name),
                required_fields=required_fields,
                important_fields=important_fields,
                excluded_fields=excluded,
                entry_type=entry_type,
            )
            for field in fields
        )
        raw_statuses.extend(field_statuses)
        raw_section_statuses.append(_section_summary(str(section_name), field_statuses))

    raw_counted = [status for status in raw_statuses if status.counted]
    raw_verified_count = sum(1 for status in raw_counted if status.state == STATE_VERIFIED_COMPLETE)
    raw_percent = _percent(raw_verified_count, len(raw_counted))
    override_requested = manual_completion_override_enabled(current_entry)
    ignored_override_fields = ignored_empty_fields_at_override(current_entry)
    override_applied = bool(override_requested and allow_manual_override)
    final_statuses = (
        _apply_manual_override(raw_statuses, ignored_override_fields) if override_applied else tuple(raw_statuses)
    )
    section_statuses = _sections_from_final_statuses(section_map, final_statuses)

    actionable_statuses = sorted(
        (status for status in final_statuses if status.is_actionable),
        key=lambda status: (status.priority, _state_sort(status.state), _field_index(section_map, status.field)),
    )
    guided_fields = tuple(status.field for status in actionable_statuses)
    next_status = actionable_statuses[0] if actionable_statuses else None
    findings = _completion_findings(current_entry, final_statuses)
    blocking_findings = [finding for finding in findings if finding.startswith(("warning:", "error:"))]
    counted = [status for status in final_statuses if status.counted]
    verified_count = sum(1 for status in counted if status.state == STATE_VERIFIED_COMPLETE)
    split_scores = calculate_split_scores(current_entry)

    percent = 100 if override_applied else _percent(verified_count, len(counted))
    return AuditCompletionSummary(
        audit_id=current_entry.get("Audit ID", ""),
        entry_type=entry_type,
        audit_context=audit_context,
        mode=mode,
        percent_complete=percent,
        raw_percent_complete=raw_percent,
        eoat_documentation_score=int(split_scores.eoat_documentation.score),
        installation_readiness_score=int(split_scores.installation_readiness.score),
        installed_cell_validation_score=split_scores.installed_cell_validation.score,
        can_finish=True if override_applied else not guided_fields and not blocking_findings,
        manual_completion_override=override_requested,
        manual_completion_override_applied=override_applied,
        manual_completion_override_timestamp=normalize_text(
            current_entry.get(MANUAL_COMPLETION_OVERRIDE_TIMESTAMP_FIELD)
        ),
        manual_completion_override_user=normalize_text(current_entry.get(MANUAL_COMPLETION_OVERRIDE_USER_FIELD)),
        ignored_empty_fields_at_override=ignored_override_fields,
        applicable_field_count=len(raw_counted),
        counted_field_count=len(counted),
        verified_complete_count=verified_count,
        missing_fields=tuple(status.field for status in final_statuses if status.state == STATE_MISSING),
        truth_missing_fields=tuple(status.field for status in final_statuses if status.truth_state == STATE_MISSING),
        unknown_not_checked_fields=tuple(
            status.field for status in final_statuses if status.state == STATE_UNKNOWN_NOT_CHECKED
        ),
        not_applicable_fields=tuple(status for status in final_statuses if status.state == STATE_NOT_APPLICABLE),
        follow_up_fields=tuple(status.field for status in final_statuses if status.state == STATE_FOLLOW_UP_NEEDED),
        not_observable_fields=tuple(status.field for status in final_statuses if status.state == STATE_NOT_OBSERVABLE),
        stale_conflict_fields=tuple(status.field for status in final_statuses if status.state == STATE_STALE_CONFLICT),
        excluded_fields=tuple(status.field for status in final_statuses if status.state == STATE_EXCLUDED),
        ignored_by_optional_group_fields=tuple(
            status.field for status in final_statuses if status.state == STATE_IGNORED_BY_OPTIONAL_GROUP
        ),
        ignored_by_manual_override_fields=tuple(
            status.field for status in final_statuses if status.state == STATE_IGNORED_BY_MANUAL_OVERRIDE
        ),
        missing_required_fields=tuple(
            status.field for status in final_statuses if status.required and status.is_actionable
        ),
        missing_important_fields=tuple(
            status.field for status in final_statuses if status.important and status.is_actionable
        ),
        guided_fields=guided_fields,
        next_best_field=next_status.field if next_status else "",
        next_best_reason="Manual completion override is applied."
        if override_applied
        else _next_best_reason(next_status),
        sections=section_statuses,
        findings=findings,
    )


def classify_completion_field(
    entry: Mapping[str, Any],
    field: str,
    *,
    section: str = "",
    required_fields: set[str] | None = None,
    important_fields: set[str] | None = None,
    excluded_fields: set[str] | frozenset[str] | tuple[str, ...] | None = None,
    entry_type: str = "",
) -> FieldCompletionStatus:
    required_fields = required_fields or set()
    important_fields = important_fields or set()
    excluded_fields = set(DEFAULT_EXCLUDED_FIELDS if excluded_fields is None else excluded_fields)
    current_entry = normalize_cylinder_fields({str(key): normalize_text(value) for key, value in entry.items()})
    value = normalize_text(current_entry.get(field))
    audit_context = infer_audit_context(current_entry)
    if audit_context == AUDIT_CONTEXT_COMPATIBILITY:
        entry_type = ENTRY_TYPE_COMPATIBLE
    spec = _spec_for_field(field)
    required = field in required_fields or spec.workbook_header in required_fields
    important = field in important_fields or spec.workbook_header in important_fields
    priority = _field_priority(field, required=required, important=important)

    base = {
        "field": field,
        "value": value,
        "section": section or spec.section,
        "group": spec.group,
        "field_id": spec.field_id,
        "workbook_header": spec.workbook_header,
        "required": required,
        "important": important,
        "priority": priority,
    }

    if field in excluded_fields or spec.workbook_header in excluded_fields:
        return FieldCompletionStatus(
            **base,
            state=STATE_EXCLUDED,
            applies=False,
            counted=False,
            verified=False,
            reason="Field is excluded from audit completion policy.",
        )

    if entry_type.casefold() == ENTRY_TYPE_COMPATIBLE.casefold() and field not in COMPATIBILITY_COMPLETION_FIELDS:
        return FieldCompletionStatus(
            **base,
            state=STATE_EXCLUDED,
            applies=False,
            counted=False,
            verified=False,
            reason="Compatibility rows use compatibility completion rules, not physical audit completion rules.",
        )

    if (
        audit_context != AUDIT_CONTEXT_COMPATIBILITY
        and field in INSTALLATION_ONLY_FIELDS
        and audit_context != AUDIT_CONTEXT_INSTALLED
    ):
        return FieldCompletionStatus(
            **base,
            state=STATE_NOT_OBSERVABLE,
            applies=False,
            counted=False,
            verified=False,
            reason="Machine-specific installation field is not observable in the current audit context.",
        )

    if field in CYLINDER_FIELDS and not cylinder_section_in_use(current_entry):
        return FieldCompletionStatus(
            **base,
            state=STATE_IGNORED_BY_OPTIONAL_GROUP,
            applies=False,
            counted=False,
            verified=False,
            reason=cylinder_optional_reason(),
        )

    if not field_applies(current_entry, field):
        reason = non_applicable_reason(current_entry, field)
        if is_meaningful_value(value):
            return FieldCompletionStatus(
                **base,
                state=STATE_STALE_CONFLICT,
                applies=False,
                counted=False,
                verified=False,
                reason=f"{reason} Current value is still populated.",
            )
        return FieldCompletionStatus(
            **base,
            state=STATE_NOT_APPLICABLE,
            applies=False,
            counted=False,
            verified=False,
            reason=reason,
        )

    if _is_unknown_not_checked(value):
        return FieldCompletionStatus(
            **base,
            state=STATE_UNKNOWN_NOT_CHECKED,
            applies=True,
            counted=True,
            verified=False,
            reason="Marked Unknown / Not Checked; explicit but not verified complete.",
        )
    if not value or is_na_value(value):
        return FieldCompletionStatus(
            **base,
            state=STATE_MISSING,
            applies=True,
            counted=True,
            verified=False,
            reason="Applicable field has not been verified.",
        )
    if _needs_follow_up(field, value):
        return FieldCompletionStatus(
            **base,
            state=STATE_FOLLOW_UP_NEEDED,
            applies=True,
            counted=True,
            verified=False,
            reason="Field is explicitly marked for review or follow-up.",
        )
    return FieldCompletionStatus(
        **base,
        state=STATE_VERIFIED_COMPLETE,
        applies=True,
        counted=True,
        verified=True,
        reason="Applicable field has a verified value.",
    )


def _apply_manual_override(
    statuses: list[FieldCompletionStatus], ignored_fields: tuple[str, ...]
) -> tuple[FieldCompletionStatus, ...]:
    ignored = {field.casefold() for field in ignored_fields}
    final: list[FieldCompletionStatus] = []
    for status in statuses:
        if status.state in ACTIONABLE_STATES:
            listed = status.field.casefold() in ignored or status.workbook_header.casefold() in ignored
            reason_suffix = " Listed in the override snapshot." if listed else ""
            final.append(
                replace(
                    status,
                    state=STATE_IGNORED_BY_MANUAL_OVERRIDE,
                    counted=False,
                    verified=False,
                    original_state=status.state,
                    reason=f"{status.reason} Ignored by manual completion override.{reason_suffix}",
                )
            )
        else:
            final.append(status)
    return tuple(final)


def _section_summary(section_name: str, statuses: tuple[FieldCompletionStatus, ...]) -> SectionCompletionStatus:
    counted = [status for status in statuses if status.counted]
    verified_count = sum(1 for status in counted if status.state == STATE_VERIFIED_COMPLETE)
    return SectionCompletionStatus(
        name=section_name,
        counted_field_count=len(counted),
        verified_complete_count=verified_count,
        missing_count=sum(1 for status in statuses if status.state == STATE_MISSING),
        unknown_not_checked_count=sum(1 for status in statuses if status.state == STATE_UNKNOWN_NOT_CHECKED),
        not_applicable_count=sum(1 for status in statuses if status.state == STATE_NOT_APPLICABLE),
        follow_up_needed_count=sum(1 for status in statuses if status.state == STATE_FOLLOW_UP_NEEDED),
        not_observable_count=sum(1 for status in statuses if status.state == STATE_NOT_OBSERVABLE),
        stale_conflict_count=sum(1 for status in statuses if status.state == STATE_STALE_CONFLICT),
        excluded_count=sum(1 for status in statuses if status.state == STATE_EXCLUDED),
        ignored_by_optional_group_count=sum(
            1 for status in statuses if status.state == STATE_IGNORED_BY_OPTIONAL_GROUP
        ),
        ignored_by_manual_override_count=sum(
            1 for status in statuses if status.state == STATE_IGNORED_BY_MANUAL_OVERRIDE
        ),
        percent_complete=_percent(verified_count, len(counted)),
        fields=statuses,
    )


def _sections_from_final_statuses(
    sections: Mapping[str, list[str] | tuple[str, ...]],
    statuses: tuple[FieldCompletionStatus, ...],
) -> tuple[SectionCompletionStatus, ...]:
    by_field = {status.field: status for status in statuses}
    return tuple(
        _section_summary(str(section_name), tuple(by_field[field] for field in fields if field in by_field))
        for section_name, fields in sections.items()
    )


def _completion_findings(entry: dict[str, str], statuses: tuple[FieldCompletionStatus, ...]) -> tuple[str, ...]:
    findings: list[str] = []
    for status in statuses:
        if status.state == STATE_STALE_CONFLICT:
            findings.append(f"warning:stale_hidden_value:{status.field}")
    for message in hybrid_completeness_warnings(entry):
        findings.append(f"warning:hybrid_warning:{message}")
    for message in semantic_consistency_warnings(entry):
        findings.append(f"warning:semantic_conflict:{message}")
    photos_taken = normalize_text(entry.get("Photos Taken?")).casefold()
    photo_link = normalize_text(entry.get("Photo Folder/Link"))
    if photos_taken == "yes" and not photo_link:
        findings.append("warning:photo_evidence:Photos are marked taken but no photo folder or link is recorded.")
    return tuple(findings)


def _spec_for_field(field: str) -> AuditFieldSpec:
    try:
        return field_by_header(field)
    except KeyError:
        folded = field.casefold()
        for spec in all_audit_fields():
            if spec.label.casefold() == folded or spec.field_id.casefold() == folded:
                return spec
    return AuditFieldSpec(
        field_id=_field_id(field),
        label=field,
        workbook_header=field,
        section="Unsectioned",
        group="Unsectioned",
    )


def _section_fields(sections: Mapping[str, list[str] | tuple[str, ...]]) -> set[str]:
    return {field for fields in sections.values() for field in fields}


def _field_id(field: str) -> str:
    import re

    text = str(field).strip().casefold().replace("#", " number ")
    return re.sub(r"[^a-z0-9]+", "_", text).strip("_") or "field"


def _field_priority(field: str, *, required: bool, important: bool) -> int:
    if required:
        return 1
    if field in EOAT_TOOLING_FIELDS:
        return 2
    if field in VISIBILITY_CONTROLLER_FIELDS:
        return 3
    if field in MAJOR_ENGINEERING_FIELDS:
        return 4
    if field_group(field) in SENSOR_PNEUMATIC_ELECTRICAL_GROUPS:
        return 5
    if field_group(field) in DOCUMENTATION_GROUPS or important:
        return 6
    return 7


def _state_sort(state: str) -> int:
    order = {
        STATE_MISSING: 0,
        STATE_STALE_CONFLICT: 1,
        STATE_UNKNOWN_NOT_CHECKED: 2,
        STATE_FOLLOW_UP_NEEDED: 3,
        STATE_NOT_OBSERVABLE: 4,
    }
    return order.get(state, 9)


def _field_index(sections: Mapping[str, list[str] | tuple[str, ...]], field: str) -> int:
    index = 0
    for fields in sections.values():
        for candidate in fields:
            if candidate == field:
                return index
            index += 1
    return 9999


def _next_best_reason(status: FieldCompletionStatus | None) -> str:
    if status is None:
        return "No applicable missing fields remain."
    if status.state == STATE_MISSING:
        return f"{status.field} is applicable and still missing."
    if status.state == STATE_UNKNOWN_NOT_CHECKED:
        return f"{status.field} is marked Unknown / Not Checked and is not verified complete."
    if status.state == STATE_FOLLOW_UP_NEEDED:
        return f"{status.field} needs follow-up before the audit can be considered verified complete."
    if status.state == STATE_STALE_CONFLICT:
        return f"{status.field} is hidden by applicability rules but still has a value."
    return status.reason


def _needs_follow_up(field: str, value: str) -> bool:
    folded = value.casefold()
    if field == "Follow-Up Needed":
        return folded == "yes"
    return "needs review" in folded or "needs follow" in folded or "follow-up" in folded


def _is_unknown_not_checked(value: str) -> bool:
    return value.casefold() in UNKNOWN_VALUES


def _percent(completed: int, total: int) -> int:
    if total <= 0:
        return 100
    return round((completed / total) * 100)


__all__ = [
    "ACTIONABLE_STATES",
    "AuditCompletionSummary",
    "DEFAULT_EXCLUDED_FIELDS",
    "FieldCompletionStatus",
    "SectionCompletionStatus",
    "STATE_EXCLUDED",
    "STATE_FOLLOW_UP_NEEDED",
    "STATE_IGNORED_BY_MANUAL_OVERRIDE",
    "STATE_IGNORED_BY_OPTIONAL_GROUP",
    "STATE_MISSING",
    "STATE_NOT_APPLICABLE",
    "STATE_NOT_OBSERVABLE",
    "STATE_STALE_CONFLICT",
    "STATE_UNKNOWN_NOT_CHECKED",
    "STATE_VERIFIED_COMPLETE",
    "UNKNOWN_NOT_CHECKED_VALUE",
    "calculate_audit_completion",
    "classify_completion_field",
]
