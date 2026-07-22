"""GUI-only, ignored per-user settings.  Secrets are never persisted."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


class GuiSettings:
    def __init__(self, name: str) -> None:
        base = (
            Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "EOAT_Atlas" / "release_tools_gui"
        )
        self.path = base / f"{name}.json"
        try:
            self.data: dict[str, Any] = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self.data = {}

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        if any(word in key.lower() for word in ("secret", "password", "token", "credential", "confirmation")):
            raise ValueError("Sensitive values cannot be saved in GUI settings")
        self.data[key] = value
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
