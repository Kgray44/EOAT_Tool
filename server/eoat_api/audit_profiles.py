"""Typed, provenance-aware projections of physical-audit records.

This is deliberately a read-model boundary: observations may fill a missing
profile value, but they never overwrite governed data or silently create a
lifecycle assignment.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

MISSING_VALUES = {"", "n/a", "na", "none", "unknown", "unknown / not checked", "not checked"}


def known_text(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text if text and text.casefold() not in MISSING_VALUES else None


def integer_value(value: Any) -> int | None:
    text = known_text(value)
    try:
        return int(text) if text is not None else None
    except ValueError:
        return None


def boolean_value(value: Any) -> bool | None:
    text = known_text(value)
    if text is None:
        return None
    if text.casefold() in {"yes", "y", "true", "present", "1"}:
        return True
    if text.casefold() in {"no", "n", "false", "not present", "0"}:
        return False
    return None


def is_physical_audit(details: dict[str, Any]) -> bool:
    """Exclude compatibility/derived rows which cite, but are not, an audit."""
    return known_text(details.get("Entry Type")) == "Audited" and not known_text(details.get("Source Audit ID"))


def configuration_from_details(details: dict[str, Any]) -> dict[str, Any]:
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
        "sensors_present": boolean_value(details.get("Sensors Present?")),
        "part_present_sensor_present": boolean_value(details.get("Part-Present Detection Present?")),
        "vacuum_confirmation_sensor_present": boolean_value(details.get("Vacuum Confirmation Present?")),
        "quick_disconnect_present": boolean_value(details.get("Quick Disconnects Present?")),
        "pneumatic_disconnect_type": known_text(details.get("Pneumatic Quick Disconnect Type")),
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
        details = dict(getattr(record, "details_json", {}) or {})
        if not is_physical_audit(details):
            continue
        identifier = known_text(getattr(record, "audit_identifier", None)) or known_text(details.get("Audit ID"))
        if not identifier:
            continue
        candidates.append(PhysicalAuditProjection(
            audit_identifier=identifier,
            audit_date=getattr(record, "audit_date", None),
            source_row_number=getattr(record, "source_row_number", None),
            observed_machine=known_text(details.get("Press/Machine #")),
            observed_tool=known_text(details.get("Tool #")),
            verified=boolean_value(details.get("Physical Audit Verified")),
            configuration=configuration_from_details(details),
        ))
    return max(
        candidates,
        key=lambda item: ((item.audit_date.date() if isinstance(item.audit_date, datetime) else item.audit_date) or date.min, item.source_row_number or 0),
        default=None,
    )
