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


def normalize_optional_hardware_values(
    *,
    eoat_type: str | None,
    vacuum_cup_count: int | None,
    gripper_count: int | None,
    sensors_present: bool | None,
    part_present_sensor_present: bool | None,
    vacuum_confirmation_sensor_present: bool | None,
) -> dict[str, int | bool | None]:
    """Apply only source-model implications that are stronger than a blank.

    The audit schema deliberately writes ``N/A`` for a field that does not
    apply.  It does *not* make every blank an absence.  Three implications are
    explicit in that source schema:

    * an exclusive Vacuum EOAT has no grippers;
    * an exclusive Mechanical / Gripper EOAT has no vacuum cups or vacuum
      confirmation sensor; and
    * a ``Sensors Present? = No`` parent makes an otherwise unspecified sensor
      presence child false.

    Hybrid, miscellaneous, blank, and unknown EOAT types deliberately retain
    nullable counts.  An explicit child value is always retained, even if an
    inconsistent source row needs review elsewhere.
    """
    normalized_type = (known_text(eoat_type) or "").casefold()
    values: dict[str, int | bool | None] = {
        "vacuum_cup_count": vacuum_cup_count,
        "gripper_count": gripper_count,
        "sensors_present": sensors_present,
        "part_present_sensor_present": part_present_sensor_present,
        "vacuum_confirmation_sensor_present": vacuum_confirmation_sensor_present,
    }
    if normalized_type == "vacuum" and values["gripper_count"] is None:
        values["gripper_count"] = 0
    if normalized_type == "mechanical / gripper":
        if values["vacuum_cup_count"] is None:
            values["vacuum_cup_count"] = 0
        if values["vacuum_confirmation_sensor_present"] is None:
            values["vacuum_confirmation_sensor_present"] = False
    if values["sensors_present"] is False:
        if values["part_present_sensor_present"] is None:
            values["part_present_sensor_present"] = False
        if values["vacuum_confirmation_sensor_present"] is None:
            values["vacuum_confirmation_sensor_present"] = False
    return values


def is_physical_audit(details: dict[str, Any]) -> bool:
    """Exclude compatibility/derived rows which cite, but are not, an audit."""
    return known_text(details.get("Entry Type")) == "Audited" and not known_text(details.get("Source Audit ID"))


def configuration_from_details(details: dict[str, Any]) -> dict[str, Any]:
    configuration = {
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
    configuration.update(normalize_optional_hardware_values(
        eoat_type=configuration["eoat_type"],
        vacuum_cup_count=configuration["vacuum_cup_count"],
        gripper_count=configuration["gripper_count"],
        sensors_present=configuration["sensors_present"],
        part_present_sensor_present=configuration["part_present_sensor_present"],
        vacuum_confirmation_sensor_present=configuration["vacuum_confirmation_sensor_present"],
    ))
    return configuration


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
