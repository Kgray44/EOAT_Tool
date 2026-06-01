from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from core.audit.completion import (
    STATE_EXCLUDED,
    STATE_IGNORED_BY_MANUAL_OVERRIDE,
    STATE_IGNORED_BY_OPTIONAL_GROUP,
    FieldCompletionStatus,
    calculate_audit_completion,
    classify_completion_field,
)
from core.audit_constants import MANUAL_COMPLETION_OVERRIDE_TIMESTAMP_FIELD, MANUAL_COMPLETION_OVERRIDE_USER_FIELD
from core.audit_field_rules import (
    field_group,
    hybrid_completeness_warnings,
    normalize_text,
    semantic_consistency_warnings,
)
from core.gripper_fields import CUP_COUNT_FIELD

STATE_VERIFIED_COMPLETE = "verified_complete"
STATE_MISSING = "missing"
STATE_UNKNOWN_NOT_CHECKED = "unknown_not_checked"
STATE_NOT_APPLICABLE = "not_applicable"
STATE_FOLLOW_UP_NEEDED = "follow_up_needed"
STATE_STALE_CONFLICT = "stale_conflict"

UNKNOWN_NOT_CHECKED_VALUE = "Unknown / Not Checked"

UNKNOWN_VALUES = {"unknown / not checked", "unknown", "not checked"}
IDENTITY_FIELDS = {"Audit ID", "Audit Date", "Auditor", "Plant/Area", "Press/Machine #", "Status"}
OPTIONAL_COMPLETION_FIELDS = {"Tubing Routing Notes", "Robot Notes", "Notes", "Final Notes"}
NON_COUNTING_COACH_OPTIONAL_FIELDS = {"Robot Notes"}
VISIBILITY_CONTROLLER_FIELDS = {
    "EOAT Type",
    "Sensors Present?",
    "Electrical/Wiring Present?",
    "Quick Disconnects Present?",
}
EOAT_TOOLING_FIELDS = {
    "Tool #",
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
    "Gripper Size",
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
    "Tubing Routing Notes",
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
class AuditCoachFieldStatus:
    field: str
    section: str
    state: str
    value: str
    applies: bool
    reason: str = ""
    priority: int = 7
    required: bool = False
    important: bool = False

    @property
    def is_actionable(self) -> bool:
        return self.state in {
            STATE_MISSING,
            STATE_UNKNOWN_NOT_CHECKED,
            STATE_FOLLOW_UP_NEEDED,
            STATE_STALE_CONFLICT,
        }


@dataclass(frozen=True)
class AuditCoachSectionStatus:
    name: str
    applicable_count: int
    verified_complete_count: int
    missing_count: int
    unknown_count: int
    not_applicable_count: int
    follow_up_count: int
    stale_conflict_count: int
    percent_complete: int
    fields: tuple[AuditCoachFieldStatus, ...] = ()


@dataclass(frozen=True)
class AuditCoachFinding:
    severity: str
    category: str
    message: str
    field: str = ""
    section: str = ""
    action: str = ""


@dataclass(frozen=True)
class AuditCoachSummary:
    audit_id: str
    entry_type: str
    mode: str
    applicable_field_count: int
    verified_complete_count: int
    missing_fields: tuple[str, ...]
    unknown_not_checked_fields: tuple[str, ...]
    not_applicable_fields: tuple[AuditCoachFieldStatus, ...]
    follow_up_fields: tuple[str, ...]
    stale_conflict_fields: tuple[str, ...]
    sections: tuple[AuditCoachSectionStatus, ...]
    findings: tuple[AuditCoachFinding, ...]
    next_best_field: str
    next_best_reason: str
    guided_fields: tuple[str, ...]
    percent_complete: int
    can_finish: bool
    missing_required_fields: tuple[str, ...] = ()
    missing_important_fields: tuple[str, ...] = ()
    manual_completion_override: bool = False
    manual_completion_override_timestamp: str = ""
    manual_completion_override_user: str = ""
    ignored_empty_fields_at_override: tuple[str, ...] = ()


def calculate_audit_coach_summary(
    entry: Mapping[str, Any],
    sections: Mapping[str, list[str] | tuple[str, ...]],
    *,
    mode: str = "",
) -> AuditCoachSummary:
    completion = calculate_audit_completion(entry, sections, mode=mode)
    current_entry = {str(key): normalize_text(value) for key, value in entry.items()}
    section_statuses: list[AuditCoachSectionStatus] = []
    all_statuses: list[AuditCoachFieldStatus] = []
    findings: list[AuditCoachFinding] = []

    for section in completion.sections:
        field_statuses = tuple(_coach_status_from_completion(status) for status in section.fields)
        all_statuses.extend(field_statuses)
        findings.extend(_stale_hidden_findings(field_statuses))
        section_statuses.append(_section_summary(section.name, field_statuses))

    findings.extend(_cross_field_findings(current_entry))
    if completion.manual_completion_override_applied:
        findings.append(
            AuditCoachFinding(
                severity="info",
                category="manual_completion_override",
                message="Manual completion override is applied. Blank fields recorded at override time are ignored for completion percentage.",
            )
        )

    missing_fields = completion.missing_fields
    unknown_fields = completion.unknown_not_checked_fields
    not_applicable = tuple(status for status in all_statuses if status.state == STATE_NOT_APPLICABLE)
    follow_up_fields = completion.follow_up_fields
    stale_conflict_fields = completion.stale_conflict_fields

    return AuditCoachSummary(
        audit_id=completion.audit_id,
        entry_type=completion.entry_type,
        mode=mode,
        applicable_field_count=completion.applicable_field_count,
        verified_complete_count=completion.verified_complete_count,
        missing_fields=missing_fields,
        unknown_not_checked_fields=unknown_fields,
        not_applicable_fields=not_applicable,
        follow_up_fields=follow_up_fields,
        stale_conflict_fields=stale_conflict_fields,
        sections=tuple(section_statuses),
        findings=tuple(findings),
        next_best_field=completion.next_best_field,
        next_best_reason=completion.next_best_reason,
        guided_fields=completion.guided_fields,
        percent_complete=completion.percent_complete,
        can_finish=completion.can_finish,
        missing_required_fields=completion.missing_required_fields,
        missing_important_fields=completion.missing_important_fields,
        manual_completion_override=completion.manual_completion_override_applied,
        manual_completion_override_timestamp=normalize_text(
            current_entry.get(MANUAL_COMPLETION_OVERRIDE_TIMESTAMP_FIELD)
        ),
        manual_completion_override_user=normalize_text(current_entry.get(MANUAL_COMPLETION_OVERRIDE_USER_FIELD)),
        ignored_empty_fields_at_override=completion.ignored_empty_fields_at_override,
    )


def classify_audit_field(
    entry: Mapping[str, Any],
    field: str,
    *,
    section: str = "",
    required_fields: set[str] | None = None,
    important_fields: set[str] | None = None,
) -> AuditCoachFieldStatus:
    status = classify_completion_field(
        entry,
        field,
        section=section,
        required_fields=required_fields,
        important_fields=important_fields,
    )
    return _coach_status_from_completion(status)


def _coach_status_from_completion(status: FieldCompletionStatus) -> AuditCoachFieldStatus:
    state = status.state
    applies = status.applies
    reason = status.reason
    required = status.required
    important = status.important
    if state == STATE_IGNORED_BY_OPTIONAL_GROUP:
        state = STATE_NOT_APPLICABLE
        applies = False
        required = False
        important = False
    elif state == STATE_EXCLUDED and status.field in NON_COUNTING_COACH_OPTIONAL_FIELDS:
        state = STATE_NOT_APPLICABLE
        applies = False
        required = False
        important = False
        reason = "Optional robot-side narrative field; excluded from audit completion percentage."
    elif state == STATE_EXCLUDED and status.field in OPTIONAL_COMPLETION_FIELDS:
        state = STATE_VERIFIED_COMPLETE
        applies = True
        required = False
        important = False
        reason = "Optional narrative field; blank is accepted."
    elif state == STATE_EXCLUDED:
        state = STATE_NOT_APPLICABLE
        applies = False
    elif state == STATE_IGNORED_BY_MANUAL_OVERRIDE:
        state = status.original_state or STATE_MISSING
    return AuditCoachFieldStatus(
        field=status.field,
        section=status.section,
        state=state,
        value=status.value,
        applies=applies,
        reason=reason,
        priority=status.priority,
        required=required,
        important=important,
    )


def unknown_not_checked_value_for_field(_field: str) -> str:
    return UNKNOWN_NOT_CHECKED_VALUE


def _section_summary(section_name: str, statuses: tuple[AuditCoachFieldStatus, ...]) -> AuditCoachSectionStatus:
    applicable = [status for status in statuses if status.applies]
    verified_count = sum(1 for status in applicable if status.state == STATE_VERIFIED_COMPLETE)
    return AuditCoachSectionStatus(
        name=section_name,
        applicable_count=len(applicable),
        verified_complete_count=verified_count,
        missing_count=sum(1 for status in statuses if status.state == STATE_MISSING),
        unknown_count=sum(1 for status in statuses if status.state == STATE_UNKNOWN_NOT_CHECKED),
        not_applicable_count=sum(1 for status in statuses if status.state == STATE_NOT_APPLICABLE),
        follow_up_count=sum(1 for status in statuses if status.state == STATE_FOLLOW_UP_NEEDED),
        stale_conflict_count=sum(1 for status in statuses if status.state == STATE_STALE_CONFLICT),
        percent_complete=_percent(verified_count, len(applicable)),
        fields=statuses,
    )


def _manual_override_section(section: AuditCoachSectionStatus) -> AuditCoachSectionStatus:
    return AuditCoachSectionStatus(
        name=section.name,
        applicable_count=section.applicable_count,
        verified_complete_count=section.applicable_count,
        missing_count=0,
        unknown_count=0,
        not_applicable_count=section.not_applicable_count,
        follow_up_count=0,
        stale_conflict_count=0,
        percent_complete=100,
        fields=section.fields,
    )


def _stale_hidden_findings(statuses: tuple[AuditCoachFieldStatus, ...]) -> list[AuditCoachFinding]:
    findings: list[AuditCoachFinding] = []
    for status in statuses:
        if status.state != STATE_STALE_CONFLICT:
            continue
        findings.append(
            AuditCoachFinding(
                severity="warning",
                category="stale_hidden_value",
                field=status.field,
                section=status.section,
                message=f"{status.field} is non-applicable but still has a value.",
                action="Review the controlling answer or save to clear the hidden value to N/A.",
            )
        )
    return findings


def _cross_field_findings(entry: dict[str, str]) -> list[AuditCoachFinding]:
    findings: list[AuditCoachFinding] = []
    for message in hybrid_completeness_warnings(entry):
        findings.append(
            AuditCoachFinding(
                severity="warning",
                category="hybrid_warning",
                message=message,
                action="Complete both vacuum-side and gripper-side details for hybrid EOAT.",
            )
        )
    for message in semantic_consistency_warnings(entry):
        findings.append(
            AuditCoachFinding(
                severity="warning",
                category="semantic_conflict",
                message=message,
                action="Review the field values that disagree with the selected EOAT configuration.",
            )
        )
    photos_taken = normalize_text(entry.get("Photos Taken?")).casefold()
    photo_link = normalize_text(entry.get("Photo Folder/Link"))
    if photos_taken == "no":
        findings.append(
            AuditCoachFinding(
                severity="info",
                category="photo_evidence",
                field="Photos Taken?",
                message="Photo evidence has not been captured for this audit.",
                action="Take photos or mark the field Unknown / Not Checked if the audit cannot verify photos yet.",
            )
        )
    if photos_taken == "yes" and not photo_link:
        findings.append(
            AuditCoachFinding(
                severity="warning",
                category="photo_evidence",
                field="Photo Folder/Link",
                message="Photos are marked taken but no photo folder or link is recorded.",
                action="Add the local folder or reference where the audit photos live.",
            )
        )
    return findings


def _field_priority(field: str, *, required: bool, important: bool) -> int:
    if required:
        return 1
    if field in EOAT_TOOLING_FIELDS:
        return 2
    if field in VISIBILITY_CONTROLLER_FIELDS:
        return 3
    if field in MAJOR_ENGINEERING_FIELDS:
        return 4
    group = field_group(field)
    if group in SENSOR_PNEUMATIC_ELECTRICAL_GROUPS:
        return 5
    if group in DOCUMENTATION_GROUPS:
        return 6
    if important:
        return 6
    return 7


def _priority_for_status(status: AuditCoachFieldStatus) -> int:
    return status.priority


def _state_sort(state: str) -> int:
    order = {
        STATE_MISSING: 0,
        STATE_STALE_CONFLICT: 1,
        STATE_UNKNOWN_NOT_CHECKED: 2,
        STATE_FOLLOW_UP_NEEDED: 3,
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


def _next_best_reason(status: AuditCoachFieldStatus | None) -> str:
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
    "AuditCoachFieldStatus",
    "AuditCoachFinding",
    "AuditCoachSectionStatus",
    "AuditCoachSummary",
    "STATE_FOLLOW_UP_NEEDED",
    "STATE_MISSING",
    "STATE_NOT_APPLICABLE",
    "STATE_STALE_CONFLICT",
    "STATE_UNKNOWN_NOT_CHECKED",
    "STATE_VERIFIED_COMPLETE",
    "UNKNOWN_NOT_CHECKED_VALUE",
    "calculate_audit_coach_summary",
    "classify_audit_field",
    "unknown_not_checked_value_for_field",
]
