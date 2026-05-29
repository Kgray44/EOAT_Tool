from __future__ import annotations

from typing import Any

from .audit.smart_rules import default_smart_default_rules
from .settings_schema import (
    CURRENT_CONFIG_SCHEMA_VERSION,
    default_backups_config,
    default_scheduled_reports_config,
    default_ui_preferences_config,
    merge_settings_dict,
)


def migrate_config_data(data: dict[str, Any]) -> dict[str, Any]:
    migrated = dict(data or {})
    migrated["config_schema_version"] = CURRENT_CONFIG_SCHEMA_VERSION

    scheduled = merge_settings_dict(default_scheduled_reports_config(), migrated.get("scheduled_reports"))
    if "daily_weekdays" not in scheduled or not isinstance(scheduled.get("daily_weekdays"), list):
        scheduled["daily_weekdays"] = list(default_scheduled_reports_config()["daily_weekdays"])
    migrated["scheduled_reports"] = scheduled

    legacy_backup = migrated.get("backup_policy")
    backups = merge_settings_dict(default_backups_config(), legacy_backup)
    backups = merge_settings_dict(backups, migrated.get("backups"))
    migrated["backups"] = backups
    migrated["backup_policy"] = _legacy_backup_policy_from_backups(backups)

    ui_preferences = merge_settings_dict(default_ui_preferences_config(), migrated.get("ui_preferences"))
    if migrated.get("theme"):
        ui_preferences["theme"] = str(migrated.get("theme"))
    if "debug_mode" in migrated:
        ui_preferences["show_debug_tools"] = bool(migrated.get("debug_mode"))
    migrated["ui_preferences"] = ui_preferences

    if "audit_coach_exclusions" not in migrated:
        migrated["audit_coach_exclusions"] = []
    if "smart_default_rules" not in migrated:
        migrated["smart_default_rules"] = default_smart_default_rules()
    if "connection_defaults" in migrated and "smart_default_rules" in migrated:
        migrated["smart_default_rules"] = _migrate_connection_defaults_to_rules(
            migrated.get("connection_defaults"),
            migrated.get("smart_default_rules"),
        )
    return migrated


def _legacy_backup_policy_from_backups(backups: dict[str, Any]) -> dict[str, Any]:
    return {
        "backup_before_workbook_migration": bool(backups.get("backup_before_workbook_migration", True)),
        "backup_before_schema_repair": bool(backups.get("backup_before_schema_repair", True)),
        "light_backup_retention_count": _safe_int(backups.get("light_backup_retention_count"), 10),
        "workbook_backup_retention_count": _safe_int(backups.get("workbook_backup_retention_count"), 20),
        "cleanup_requires_validation": bool(backups.get("cleanup_requires_validation", True)),
    }


def _safe_int(value: Any, fallback: int) -> int:
    try:
        parsed = int(str(value or "").strip())
    except ValueError:
        return fallback
    return parsed if parsed >= 0 else fallback


def _string_dict(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key): "" if item is None else str(item) for key, item in value.items()}


def _rule_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _migrate_connection_defaults_to_rules(connection_defaults: Any, existing_rules: Any) -> list[dict[str, Any]]:
    rules = _rule_list(existing_rules)
    existing_ids = {str(rule.get("id") or "") for rule in rules}
    for key, value in _string_dict(connection_defaults).items():
        rule_id = f"connection_default_{key.lower().replace(' ', '_')}"
        if rule_id in existing_ids:
            continue
        rules.append(
            {
                "id": rule_id,
                "enabled": True,
                "when_field": "Connection Type",
                "operator": "contains",
                "when_value": key,
                "set_field": "Changeover Difficulty",
                "set_value": value,
                "source": "migrated_connection_defaults",
            }
        )
    return rules


__all__ = ["migrate_config_data"]
