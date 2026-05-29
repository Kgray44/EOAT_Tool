from __future__ import annotations

from core.audit.defaults import DEFAULT_AUDIT_DEFAULTS, DEFAULT_CONNECTION_DEFAULTS

AUDIT_DEFAULT_SETTING_FIELDS = [
    "Auditor",
    "Plant/Area",
    "Cleanroom/Non-Cleanroom",
    "Status",
    "Priority",
    "Follow-Up Needed",
    "Quick Disconnects Present?",
    "Pneumatic Quick Disconnect Type",
    "Vacuum Generator Type",
    "EOAT Interchangeable Circuits",
    "Robot Interchangeable Circuits",
    "Photos Taken?",
]

CONNECTION_DEFAULT_SETTING_FIELDS = ["ATI", "DoveTail"]

SETTINGS_SECTION_TITLES = [
    "Project & Data",
    "Audit Defaults",
    "Smart Rules",
    "Scheduled Reports",
    "Backups & Safety",
    "UI Preferences",
    "External Tools",
    "Advanced / Diagnostics",
]

DEFAULT_AUDIT_SETTING_VALUES = DEFAULT_AUDIT_DEFAULTS
DEFAULT_CONNECTION_SETTING_VALUES = DEFAULT_CONNECTION_DEFAULTS


__all__ = [
    "AUDIT_DEFAULT_SETTING_FIELDS",
    "CONNECTION_DEFAULT_SETTING_FIELDS",
    "DEFAULT_AUDIT_SETTING_VALUES",
    "DEFAULT_CONNECTION_SETTING_VALUES",
    "SETTINGS_SECTION_TITLES",
]
