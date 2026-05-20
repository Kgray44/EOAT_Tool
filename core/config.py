from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

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

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "UserConfig":
        defaults = asdict(cls())
        defaults.update({key: value for key, value in data.items() if key in defaults})
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
