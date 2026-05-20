from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path

from .result import ToolResult


def open_path(path: str | Path) -> ToolResult:
    target = Path(path)
    if not target.exists():
        return ToolResult.fail(
            "open_path",
            "Open File or Folder",
            "Path does not exist.",
            errors=[str(target)],
        )
    try:
        if platform.system() == "Windows" and hasattr(os, "startfile"):
            os.startfile(target)  # type: ignore[attr-defined]
        elif platform.system() == "Darwin":
            subprocess.Popen(["open", str(target)])
        else:
            subprocess.Popen(["xdg-open", str(target)])
    except Exception as exc:
        return ToolResult.fail(
            "open_path",
            "Open File or Folder",
            "Could not open path.",
            errors=[str(exc)],
        )
    return ToolResult.ok("open_path", "Open File or Folder", f"Opened: {target}")

