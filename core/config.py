from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .audit.defaults import DEFAULT_AUDIT_DEFAULTS, DEFAULT_CONNECTION_DEFAULTS
from .audit.default_rules import normalize_default_rules
from .audit.smart_rules import default_smart_default_rules
from .config_migration import migrate_config_data
from .constants import DEFAULT_CONFIG_PATH, DEFAULT_GIT_EXECUTABLE, DEFAULT_PROJECT_ROOT, LEGACY_CONFIG_PATH
from .safe_files import ensure_directory
from .settings_schema import (
    CURRENT_CONFIG_SCHEMA_VERSION,
    default_backups_config,
    default_scheduled_reports_config,
    default_ui_preferences_config,
    merge_settings_dict,
)


@dataclass
class UserConfig:
    config_schema_version: int = CURRENT_CONFIG_SCHEMA_VERSION
    project_root: str = str(DEFAULT_PROJECT_ROOT)
    debug_mode: bool = False
    theme: str = "light"
    git_executable: str = str(DEFAULT_GIT_EXECUTABLE)
    project_start_date: str = ""
    workdays: list[str] = field(default_factory=lambda: ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"])
    skip_weekends: bool = True
    holidays: list[str] = field(default_factory=list)
    audit_defaults: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_AUDIT_DEFAULTS))
    audit_default_rules: list[dict[str, Any]] = field(default_factory=list)
    connection_defaults: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_CONNECTION_DEFAULTS))
    scheduled_reports: dict[str, Any] = field(default_factory=lambda: default_scheduled_reports_config())
    backups: dict[str, Any] = field(default_factory=lambda: default_backups_config())
    backup_policy: dict[str, Any] = field(default_factory=lambda: _legacy_backup_policy_from_backups(default_backups_config()))
    ui_preferences: dict[str, Any] = field(default_factory=lambda: default_ui_preferences_config())
    audit_coach_exclusions: list[str] = field(default_factory=list)
    smart_default_rules: list[dict[str, Any]] = field(default_factory=lambda: default_smart_default_rules())
    extra_config: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "UserConfig":
        migrated = migrate_config_data(data)
        known_fields = set(cls.__dataclass_fields__)
        defaults = asdict(cls())
        defaults.update({key: value for key, value in migrated.items() if key in known_fields and key != "extra_config"})
        defaults["extra_config"] = {key: value for key, value in migrated.items() if key not in known_fields}
        audit_defaults = dict(DEFAULT_AUDIT_DEFAULTS)
        audit_defaults.update(_string_dict(defaults.get("audit_defaults")))
        connection_defaults = dict(DEFAULT_CONNECTION_DEFAULTS)
        connection_defaults.update(_string_dict(defaults.get("connection_defaults")))
        defaults["audit_defaults"] = audit_defaults
        defaults["audit_default_rules"] = [rule.to_dict() for rule in normalize_default_rules(defaults.get("audit_default_rules"))]
        defaults["connection_defaults"] = connection_defaults
        defaults["scheduled_reports"] = merge_settings_dict(default_scheduled_reports_config(), defaults.get("scheduled_reports"))
        defaults["backups"] = merge_settings_dict(default_backups_config(), defaults.get("backups"))
        defaults["backup_policy"] = _legacy_backup_policy_from_backups(defaults["backups"])
        defaults["ui_preferences"] = merge_settings_dict(default_ui_preferences_config(), defaults.get("ui_preferences"))
        defaults["theme"] = str(defaults["ui_preferences"].get("theme") or defaults.get("theme") or "light")
        defaults["debug_mode"] = bool(defaults["ui_preferences"].get("show_debug_tools", defaults.get("debug_mode", False)))
        defaults["audit_coach_exclusions"] = _string_list(defaults.get("audit_coach_exclusions"))
        defaults["smart_default_rules"] = _rule_list(defaults.get("smart_default_rules"))
        return cls(**defaults)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        extra = dict(data.pop("extra_config", {}) or {})
        extra.update(data)
        extra["ui_preferences"] = merge_settings_dict(
            default_ui_preferences_config(),
            {**dict(extra.get("ui_preferences") or {}), "theme": self.theme, "show_debug_tools": self.debug_mode},
        )
        extra["backup_policy"] = _legacy_backup_policy_from_backups(extra.get("backups", {}))
        return extra


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


def default_backup_policy_config() -> dict[str, Any]:
    return _legacy_backup_policy_from_backups(default_backups_config())


def _string_dict(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key): "" if item is None else str(item) for key, item in value.items()}


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item or "").strip()]


def _rule_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


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
