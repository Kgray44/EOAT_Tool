from __future__ import annotations

import json
from pathlib import Path

LAUNCHER_NAME = "EOAT Atlas Launcher"
LAUNCHER_VERSION = str(
    json.loads(Path(__file__).with_name("launcher_version.json").read_text(encoding="utf-8"))["launcher_version"]
)

__all__ = ["LAUNCHER_NAME", "LAUNCHER_VERSION"]
