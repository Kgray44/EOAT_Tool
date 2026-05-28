from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .audit.defaults import DEFAULT_AUDIT_DEFAULTS, DEFAULT_CONNECTION_DEFAULTS
from .audit.smart_rules import default_smart_default_rules
from .constants import DEFAULT_CONFIG_PATH, DEFAULT_GIT_EXECUTABLE, DEFAULT_PROJECT_ROOT, LEGACY_CONFIG_PATH
from .safe_files import ensure_directory


@dataclass
class UserConfig:
    config_schema_version: int = 2
    project_root: str = str(DEFAULT_PROJECT_ROOT)
    debug_mode: bool = False
    theme: str = "light"
    git_executable: str = str(DEFAULT_GIT_EXECUTABLE)
    project_start_date: str = ""
    workdays: list[str] = field(default_factory=lambda: ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"])
    skip_weekends: bool = True
    holidays: list[str] = field(default_factory=list)
    audit_defaults: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_AUDIT_DEFAULTS))
    connection_defaults: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_CONNECTION_DEFAULTS))
    scheduled_reports: dict[str, Any] = field(default_factory=lambda: default_scheduled_reports_config())
    backup_policy: dict[str, Any] = field(default_factory=lambda: default_backup_policy_config())
    audit_coach_exclusions: list[str] = field(default_factory=list)
    smart_default_rules: list[dict[str, Any]] = field(default_factory=lambda: default_smart_default_rules())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "UserConfig":
        migrated = migrate_config_data(data)
        defaults = asdict(cls())
        defaults.update({key: value for key, value in migrated.items() if key in defaults})
        audit_defaults = dict(DEFAULT_AUDIT_DEFAULTS)
        audit_defaults.update(_string_dict(defaults.get("audit_defaults")))
        connection_defaults = dict(DEFAULT_CONNECTION_DEFAULTS)
        connection_defaults.update(_string_dict(defaults.get("connection_defaults")))
        defaults["audit_defaults"] = audit_defaults
        defaults["connection_defaults"] = connection_defaults
        defaults["scheduled_reports"] = _merged_dict(default_scheduled_reports_config(), defaults.get("scheduled_reports"))
        defaults["backup_policy"] = _merged_dict(default_backup_policy_config(), defaults.get("backup_policy"))
        defaults["audit_coach_exclusions"] = _string_list(defaults.get("audit_coach_exclusions"))
        defaults["smart_default_rules"] = _rule_list(defaults.get("smart_default_rules"))
        return cls(**defaults)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_config(config_path: str | Path = DEFAULT_CONFIG_PATH) -> UserConfig:
    path = Path(config_path)
    if path == Path(DEFAULT_CONFIG_PATH) and not path.exists() and LEGACY_CONFIG_PATH.exists():
        path = LEGACY_CONFIG_PATH
    if not path.exists():
        return UserConfig()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return UserConfig()
    if not isinstance(data, dict):
        return UserConfig()
    return UserConfig.from_dict(data)


def save_config(config: UserConfig, config_path: str | Path = DEFAULT_CONFIG_PATH) -> Path:
    path = Path(config_path)
    ensure_directory(path.parent)
    path.write_text(json.dumps(config.to_dict(), indent=2), encoding="utf-8")
    return path


def default_scheduled_reports_config() -> dict[str, Any]:
    return {
        "daily_enabled": True,
        "weekly_enabled": True,
        "daily_time": "19:00",
        "weekly_time": "19:00",
        "timezone": "America/New_York",
        "prevent_overwrite": True,
    }


def default_backup_policy_config() -> dict[str, Any]:
    return {
        "backup_before_workbook_migration": True,
        "backup_before_schema_repair": True,
        "light_backup_retention_count": 10,
        "workbook_backup_retention_count": 20,
        "cleanup_requires_validation": True,
    }


def migrate_config_data(data: dict[str, Any]) -> dict[str, Any]:
    migrated = dict(data or {})
    migrated["config_schema_version"] = 2
    if "scheduled_reports" not in migrated:
        migrated["scheduled_reports"] = default_scheduled_reports_config()
    if "backup_policy" not in migrated:
        migrated["backup_policy"] = default_backup_policy_config()
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


def _string_dict(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key): "" if item is None else str(item) for key, item in value.items()}


def _merged_dict(defaults: dict[str, Any], value: Any) -> dict[str, Any]:
    merged = dict(defaults)
    if isinstance(value, dict):
        merged.update(value)
    return merged


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item or "").strip()]


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
