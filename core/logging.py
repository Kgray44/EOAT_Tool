from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .paths import resolve_project_paths
from .result import ToolResult
from .safe_files import ensure_directory


def activity_log_path(project_root: str | Path) -> Path:
    return resolve_project_paths(project_root).activity_logs / "activity_log.jsonl"


def log_tool_run(result: ToolResult, project_root: str | Path) -> str | None:
    try:
        path = activity_log_path(project_root)
        ensure_directory(path.parent)
        entry: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "tool_id": result.tool_id,
            "tool_name": result.tool_name,
            "success": result.success,
            "project_root": str(project_root),
            "files_created": result.files_created,
            "files_modified": result.files_modified,
            "warnings": result.warnings,
            "errors": result.errors,
            "duration_seconds": result.duration_seconds,
            "summary": result.summary,
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=True) + "\n")
    except Exception as exc:
        return f"Activity logging failed: {exc}"
    return None


def log_activity_event(project_root: str | Path, event_name: str, payload: dict[str, Any]) -> str | None:
    try:
        path = activity_log_path(project_root)
        ensure_directory(path.parent)
        entry: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_name": event_name,
            "project_root": str(project_root),
            **payload,
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=True) + "\n")
    except Exception as exc:
        return f"Activity logging failed: {exc}"
    return None


def read_last_activity(project_root: str | Path) -> dict[str, Any] | None:
    path = activity_log_path(project_root)
    if not path.exists():
        return None
    try:
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if not lines:
            return None
        return json.loads(lines[-1])
    except Exception:
        return None


def read_recent_activity(project_root: str | Path, limit: int = 25) -> tuple[list[dict[str, Any]], str | None]:
    path = activity_log_path(project_root)
    if not path.exists():
        return [], None
    entries: list[dict[str, Any]] = []
    warning: str | None = None
    try:
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except OSError as exc:
        return [], f"Could not read activity log: {exc}"
    for line in lines[-limit:]:
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            warning = "Some activity log lines could not be parsed."
    entries.reverse()
    return entries, warning
