from __future__ import annotations

from collections.abc import Mapping
from typing import Any

DEFAULT_AUDITOR = "Kato Gray"
UNKNOWN_NOT_CHECKED = "Unknown / Not Checked"

DEFAULT_AUDIT_DEFAULTS: dict[str, str] = {
    "Auditor": DEFAULT_AUDITOR,
    "Plant/Area": "Plant 4",
    "Cleanroom/Non-Cleanroom": "Whiteroom",
    "Status": "In Progress",
    "Priority": "Medium",
    "Follow-Up Needed": "No",
    "Quick Disconnects Present?": "Yes",
    "Pneumatic Quick Disconnect Type": "PTC",
    "Vacuum Generator Type": "Venturi",
    "EOAT Interchangeable Circuits": "0",
    "Robot Interchangeable Circuits": "0",
    "Electrical/Wiring Present?": UNKNOWN_NOT_CHECKED,
    "Known Issues": UNKNOWN_NOT_CHECKED,
    "Drop/Mis-Pick History": UNKNOWN_NOT_CHECKED,
    "Maintenance Frequency": UNKNOWN_NOT_CHECKED,
    "Sensors Present?": UNKNOWN_NOT_CHECKED,
    "Tubing Condition": UNKNOWN_NOT_CHECKED,
    "Cable Management Condition": UNKNOWN_NOT_CHECKED,
    "Mounting Hardware Condition": UNKNOWN_NOT_CHECKED,
    "EOAT Alignment Condition": UNKNOWN_NOT_CHECKED,
    "Fastener/Locking Hardware Present?": UNKNOWN_NOT_CHECKED,
    "Cycle Time Concern?": UNKNOWN_NOT_CHECKED,
    "Scrap/Quality Concern?": UNKNOWN_NOT_CHECKED,
    "Changeover Difficulty": UNKNOWN_NOT_CHECKED,
    "Spare Parts Identified?": "No",
    "Drawing/CAD Available?": "No",
    "BOM Available?": "No",
    "Process Binder Complete?": "No",
    "Photos Taken?": "No",
    "Vacuum Confirmation Present?": "Yes",
    "Part-Present Detection Present?": "No",
    "Cup Type/Material": "Silicone",
    "Cylinder Type": "Linear",
}

DEFAULT_CONNECTION_DEFAULTS: dict[str, str] = {
    "ATI": "Low",
    "DoveTail": "Medium",
    "Dove Tail": "Medium",
}


def _string_dict(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): "" if item is None else str(item) for key, item in value.items()}


def merged_audit_defaults(config: Any | None = None) -> dict[str, str]:
    defaults = dict(DEFAULT_AUDIT_DEFAULTS)
    defaults.update(_string_dict(getattr(config, "audit_defaults", {})))
    return defaults


def merged_connection_defaults(config: Any | None = None) -> dict[str, str]:
    defaults = dict(DEFAULT_CONNECTION_DEFAULTS)
    defaults.update(_string_dict(getattr(config, "connection_defaults", {})))
    return defaults


def audit_default(field_name: str, config: Any | None = None) -> str | None:
    return merged_audit_defaults(config).get(field_name)


def connection_changeover_default(connection_type: str, config: Any | None = None) -> str | None:
    text = str(connection_type or "").strip().casefold()
    if not text:
        return None
    for key, value in merged_connection_defaults(config).items():
        normalized_key = str(key or "").strip().casefold()
        if normalized_key and normalized_key in text:
            return value
    return None
