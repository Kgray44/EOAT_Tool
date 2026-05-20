from __future__ import annotations

import json
from pathlib import Path

from core.config import UserConfig


def create_fake_config(project_root: str | Path, config_path: str | Path | None = None) -> UserConfig:
    config = UserConfig(
        project_root=str(project_root),
        debug_mode=True,
        theme="light",
        git_executable="",
        project_start_date="2026-05-18",
        workdays=["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
        skip_weekends=True,
        holidays=[],
    )
    if config_path is not None:
        path = Path(config_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(config.to_dict(), indent=2), encoding="utf-8")
    return config
