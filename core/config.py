from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .audit.defaults import DEFAULT_AUDIT_DEFAULTS, DEFAULT_CONNECTION_DEFAULTS
from .constants import DEFAULT_CONFIG_PATH, DEFAULT_GIT_EXECUTABLE, DEFAULT_PROJECT_ROOT, LEGACY_CONFIG_PATH
from .safe_files import ensure_directory


@dataclass
class UserConfig:
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

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "UserConfig":
        defaults = asdict(cls())
        defaults.update({key: value for key, value in data.items() if key in defaults})
        audit_defaults = dict(DEFAULT_AUDIT_DEFAULTS)
        audit_defaults.update(_string_dict(defaults.get("audit_defaults")))
        connection_defaults = dict(DEFAULT_CONNECTION_DEFAULTS)
        connection_defaults.update(_string_dict(defaults.get("connection_defaults")))
        defaults["audit_defaults"] = audit_defaults
        defaults["connection_defaults"] = connection_defaults
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


def _string_dict(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key): "" if item is None else str(item) for key, item in value.items()}
