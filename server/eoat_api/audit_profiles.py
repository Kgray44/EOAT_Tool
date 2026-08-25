"""Typed, provenance-aware projections of physical-audit records.

The import keeps every tracker row in ``audit_records.details_json``.  This
module is the single read-model boundary that turns a *physical* audit row
into profile evidence without promoting that historical observation to a
present-day assignment.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

MISSING_VALUES = {"", "n/a", "na", "none", "unknown", "unknown / not checked", "not checked"}


def text_value(value: Any) -> str | None:
    value = str(value).strip() if value is not None else ""
    return value or None


def known_text(value: Any) -> str | None:
    value = text_value(value)
    return value if value and value.casefold() not in MISSING_VALUES else None


def integer_value(value: Any) -> int | None:
    text = known_text(value)
    if text is None:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def boolean_value(value: Any) -> bool | None:
    text = known_text(value)
    if text is None:
        return None
    normalized = text.casefold()
    if normalized in {"yes", "y", "true", "present", "1"}:
        return True
    if normalized in {"no", "n", "false", "not present", "0"}:
        return False
    return None


def is_physical_audit(details: dict[str, Any]) -> bool:
    """Return true only for a tracker row that is an actual physical audit.

    Compatible/derived rows may cite a physical audit but must not become an
    observation themselves.
    """

    return text_value(details.get("Entry Type")) == "Audited" and not text_value(details.get("Source Audit ID"))


def audit_sort_key(audit_date: datetime | date | None, source_row_number: int | None) -> tuple[date, int]:
    if isinstance(audit_date, datetime):
        audit_date = audit_date.date()
    return (audit_date or date.min, int(source_row_number or 0))


def configuration_from_details(details: dict[str, Any]) -> dict[str, Any]:
    """Project only meaningful tracker values, preserving null for unknown."""

    return {
        "description": known_text(details.get("Part Name/Description")),
        "eoat_type": known_text(details.get("EOAT Type")),
        "connection_type": known_text(details.get("Connection Type")),
        "cleanroom_classification": known_text(details.get("Cleanroom/Non-Cleanroom")),
        "parts_picked": integer_value(details.get("Number of Parts Picked")),
        "vacuum_cup_count": integer_value(details.get("# of Cups")),
        "gripper_count": integer_value(details.get("# of Grippers")),
        "cup_material": known_text(details.get("Cup Type/Material")),
        "cup_size": known_text(details.get("Cup Diameter/Size")),
        "vacuum_generator": known_text(details.get("Vacuum Generator Type")),
        "vacuum_circuits": integer_value(details.get("EOAT Vacuum Circuits")),
        "pressure_circuits": integer_value(details.get("EOAT Pressure Circuits")),
        "gripper_type": known_text(details.get("Gripper Type")),
        "gripper_model": known_text(details.get("Gripper Model")),
        "sensors_present": boolean_value(details.get("Sensors Present?")),
        "part_present_sensor_present": boolean_value(details.get("Part-Present Detection Present?")),
        "vacuum_confirmation_sensor_present": boolean_value(details.get("Vacuum Confirmation Present?")),
        "quick_disconnect_present": boolean_value(details.get("Quick Disconnects Present?")),
        "pneumatic_disconnect_type": known_text(details.get("Pneumatic Quick Disconnect Type")),
        "electrical_disconnect_type": known_text(details.get("Electrical Quick Disconnect Type")),
        "electrical_wiring_present": boolean_value(details.get("Electrical/Wiring Present?")),
    }


@dataclass(frozen=True)
class PhysicalAuditProjection:
    audit_identifier: str
    audit_date: datetime | date | None
    source_row_number: int | None
    observed_machine: str | None
    observed_tool: str | None
    verified: bool | None
    configuration: dict[str, Any]


def latest_physical_audit(records: Iterable[Any]) -> PhysicalAuditProjection | None:
    candidates: list[PhysicalAuditProjection] = []
    for record in records:
        details_source = (
            record.get("details_json", {})
            if isinstance(record, dict)
            else getattr(record, "details_json", {})
        )
        details = dict(details_source or {})
        if not is_physical_audit(details):
            continue
        identifier = text_value(
            getattr(record, "audit_identifier", None)
            if not isinstance(record, dict)
            else record.get("audit_identifier")
        )
        identifier = identifier or text_value(details.get("Audit ID"))
        if not identifier:
            continue
        candidates.append(
            PhysicalAuditProjection(
                audit_identifier=identifier,
                audit_date=(
                    getattr(record, "audit_date", None)
                    if not isinstance(record, dict)
                    else record.get("audit_date")
                ),
                source_row_number=(
                    getattr(record, "source_row_number", None)
                    if not isinstance(record, dict)
                    else record.get("source_row_number")
                ),
                observed_machine=known_text(details.get("Press/Machine #")),
                observed_tool=known_text(details.get("Tool #")),
                verified=boolean_value(details.get("Physical Audit Verified")),
                configuration=configuration_from_details(details),
            )
        )
    return max(candidates, key=lambda value: audit_sort_key(value.audit_date, value.source_row_number), default=None)


__all__ = [
    "PhysicalAuditProjection",
    "audit_sort_key",
    "boolean_value",
    "configuration_from_details",
    "integer_value",
    "is_physical_audit",
    "latest_physical_audit",
    "known_text",
]
