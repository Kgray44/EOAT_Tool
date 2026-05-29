from __future__ import annotations

from typing import Any

CURRENT_CONFIG_SCHEMA_VERSION = 2

SCHEDULED_REPORT_WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
SCHEDULED_REPORT_DUPLICATE_POLICIES = ["skip_existing", "overwrite", "version_copy"]
SCHEDULED_REPORT_MISSED_RUN_POLICIES = ["catch_up", "skip", "warn_only"]


def default_scheduled_reports_config() -> dict[str, Any]:
    return {
        "daily_enabled": True,
        "daily_weekdays": ["Monday", "Tuesday", "Wednesday", "Thursday"],
        "daily_time": "19:00",
        "weekly_enabled": True,
        "weekly_weekday": "Friday",
        "weekly_time": "19:00",
        "timezone": "America/New_York",
        "duplicate_policy": "skip_existing",
        "missed_run_policy": "catch_up",
        "dry_run_folder": "",
        "prevent_overwrite": True,
    }


def default_backups_config() -> dict[str, Any]:
    return {
        "backup_before_audit_save": True,
        "backup_before_compatibility_update": True,
        "backup_before_workbook_migration": True,
        "backup_before_bulk_repair": True,
        "backup_before_schema_repair": True,
        "retention_days": 7,
        "newest_backups_per_workbook": 25,
        "keep_milestones": True,
        "cleanup_requires_preview": True,
        "cleanup_blocked_by_validation_blockers": True,
        "light_backup_retention_count": 10,
        "workbook_backup_retention_count": 20,
        "cleanup_requires_validation": True,
    }


def default_ui_preferences_config() -> dict[str, Any]:
    return {
        "theme": "light",
        "show_debug_tools": False,
        "settings_open_section": "Project & Data",
    }


def merge_settings_dict(defaults: dict[str, Any], value: Any) -> dict[str, Any]:
    merged = dict(defaults)
    if isinstance(value, dict):
        merged.update(value)
    return merged


__all__ = [
    "CURRENT_CONFIG_SCHEMA_VERSION",
    "SCHEDULED_REPORT_DUPLICATE_POLICIES",
    "SCHEDULED_REPORT_MISSED_RUN_POLICIES",
    "SCHEDULED_REPORT_WEEKDAYS",
    "default_backups_config",
    "default_scheduled_reports_config",
    "default_ui_preferences_config",
    "merge_settings_dict",
]
