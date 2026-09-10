"""Controlled EOAT data carried forward from the Command Center audit form.

This module deliberately models the Command Center's data contract, not its
desktop presentation.  Values already normalized on ``EOAT`` remain there;
the remaining inspection, interface, and reliability details are retained on
the authoritative engineering profile as one versioned structured record.
"""
from __future__ import annotations

from typing import Any

from .errors import APIError

UNKNOWN = "Unknown / Not Checked"
NOT_APPLICABLE = "N/A"

COMMAND_CENTER_OPTIONS: dict[str, tuple[str, ...]] = {
    "audit_context": (
        "Installed on Machine",
        "Not Installed / Bench Audit",
        "Compatibility row",
        "Historical/imported",
        "Needs review",
    ),
    "status": ("Not Started", "In Progress", "Complete", "Needs Follow-Up", "Blocked"),
    "priority": ("Low", "Medium", "High", "Critical"),
    "follow_up_needed": ("Yes", "No"),
    "eoat_moves": ("Part", "Sprue", "Both"),
    "robot_type": ("Wittmann R8", "Wittmann R9", "Engel Viper", "Other", "Unknown"),
    "air_circuit_architecture": (
        "Robot Only",
        "External Peripheral Only",
        "Mixed Robot + External Peripheral",
        "Unknown / Needs Verification",
    ),
    "tubing_condition": ("OK", "Worn", "Damaged", "Poor Routing", "Needs Follow-Up", UNKNOWN),
    "cable_management_condition": ("OK", "Loose", "Damaged", "Poor Routing", "Needs Follow-Up", UNKNOWN),
    "mounting_hardware_condition": ("OK", "Loose", "Missing Hardware", "Damaged", "Needs Follow-Up", UNKNOWN),
    "eoat_alignment_condition": ("OK", "Slightly Off", "Misaligned", "Needs Follow-Up", UNKNOWN),
    "fastener_locking_hardware_present": ("Yes", "No", "Partial", UNKNOWN),
    "cycle_time_concern": ("Yes", "No", UNKNOWN),
    "scrap_quality_concern": ("Yes", "No", UNKNOWN),
    "changeover_difficulty": ("Easy", "Low", "Medium", "High", UNKNOWN),
    "spare_parts_identified": ("Yes", "No", "Partial", UNKNOWN),
    "drawing_cad_available": ("Yes", "No", UNKNOWN),
    "bom_available": ("Yes", "No", UNKNOWN),
    "process_binder_complete": ("Yes", "No", "Partial", UNKNOWN),
    "photos_taken": ("Yes", "No"),
    "pilot_candidate": ("Yes", "No", "Maybe"),
}

COMMAND_CENTER_NUMERIC_FIELDS = frozenset(
    {
        "robot_vacuum_circuits",
        "robot_pressure_circuits",
        "robot_interchangeable_circuits",
        "external_vacuum_circuits",
        "external_pressure_circuits",
        "external_interchangeable_circuits",
    }
)

COMMAND_CENTER_DEFAULTS: dict[str, Any] = {
    "status": "In Progress",
    "priority": "Medium",
    "follow_up_needed": "No",
    "air_circuit_architecture": "Robot Only",
    "robot_interchangeable_circuits": 0,
    "external_vacuum_circuits": NOT_APPLICABLE,
    "external_pressure_circuits": NOT_APPLICABLE,
    "external_interchangeable_circuits": NOT_APPLICABLE,
    "tubing_condition": UNKNOWN,
    "cable_management_condition": UNKNOWN,
    "mounting_hardware_condition": UNKNOWN,
    "eoat_alignment_condition": UNKNOWN,
    "fastener_locking_hardware_present": UNKNOWN,
    "cycle_time_concern": UNKNOWN,
    "scrap_quality_concern": UNKNOWN,
    "changeover_difficulty": UNKNOWN,
    "spare_parts_identified": "No",
    "drawing_cad_available": "No",
    "bom_available": "No",
    "process_binder_complete": "No",
    "photos_taken": "No",
    "pilot_candidate": "No",
    "pneumatic_quick_disconnect_type": "PTC",
}

COMMAND_CENTER_FIELDS = frozenset(
    {
        *COMMAND_CENTER_OPTIONS,
        *COMMAND_CENTER_NUMERIC_FIELDS,
        "robot_model_controller",
        "part_family",
        "part_name_description",
        "robot_notes",
        "tubing_routing_notes",
        "known_issues",
        "drop_mispick_history",
        "maintenance_frequency",
        "pneumatic_quick_disconnect_type",
        "electrical_quick_disconnect_type",
    }
)


def command_center_defaults() -> dict[str, Any]:
    """Return a fresh, explicit default set for a new onboarding draft."""
    return dict(COMMAND_CENTER_DEFAULTS)


def normalize_command_center_data(value: Any) -> dict[str, Any]:
    """Validate controlled values without converting unknown into a fact."""
    if value is None:
        return command_center_defaults()
    if not isinstance(value, dict):
        raise APIError(422, "COMMAND_CENTER_DATA_INVALID", "Command Center onboarding data must be an object.")
    unknown_fields = sorted(set(value) - COMMAND_CENTER_FIELDS)
    if unknown_fields:
        raise APIError(
            422,
            "COMMAND_CENTER_DATA_INVALID",
            f"Unsupported Command Center field: {unknown_fields[0]}.",
        )
    normalized = command_center_defaults()
    for key, raw in value.items():
        if raw is None or raw == "":
            normalized[key] = None
            continue
        if key in COMMAND_CENTER_NUMERIC_FIELDS:
            if isinstance(raw, bool):
                raise APIError(422, "COMMAND_CENTER_DATA_INVALID", f"{key} must be a non-negative count.")
            if isinstance(raw, str) and raw.strip().isdigit():
                normalized[key] = int(raw.strip())
                continue
            if isinstance(raw, int) and raw >= 0:
                normalized[key] = raw
                continue
            if isinstance(raw, str) and raw.strip() in {NOT_APPLICABLE, UNKNOWN}:
                normalized[key] = raw.strip()
                continue
            raise APIError(422, "COMMAND_CENTER_DATA_INVALID", f"{key} must be a non-negative count, N/A, or unknown.")
        text = str(raw).strip()
        options = COMMAND_CENTER_OPTIONS.get(key)
        if options and text not in options:
            raise APIError(422, "COMMAND_CENTER_DATA_INVALID", f"{key} must use a controlled Command Center option.")
        normalized[key] = text
    return normalized
