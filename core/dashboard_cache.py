from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .paths import resolve_project_paths
from .safe_files import ensure_directory

CACHE_VERSION = 1


def dashboard_cache_path(project_root: str | Path) -> Path:
    return resolve_project_paths(project_root).cache / "dashboard_snapshot.json"


def _file_metadata(path: Path) -> dict[str, Any]:
    try:
        stat = path.stat()
    except OSError:
        return {"path": str(path), "exists": False, "mtime": None, "size": None}
    return {"path": str(path), "exists": True, "mtime": stat.st_mtime, "size": stat.st_size}


def source_metadata(project_root: str | Path) -> dict[str, Any]:
    paths = resolve_project_paths(project_root)
    files = [
        paths.master_workbook,
        paths.activity_logs / "activity_log.jsonl",
    ]
    files.extend(paths.project_admin.glob("project_schedule_week*.json") if paths.project_admin.exists() else [])
    files.extend(paths.project_admin.glob("task_progress_week*.json") if paths.project_admin.exists() else [])
    for folder in [paths.daily_reports, paths.weekly_reports, paths.validation_reports, paths.audit_progress_reports]:
        if folder.exists():
            files.extend(path for path in folder.glob("*") if path.is_file())
    return {"files": [_file_metadata(path) for path in sorted(set(files), key=lambda item: str(item))]}


def load_dashboard_cache(project_root: str | Path) -> tuple[dict[str, Any] | None, str | None]:
    path = dashboard_cache_path(project_root)
    if not path.exists():
        return None, "No dashboard cache found."
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"Could not load dashboard cache: {exc}"
    if not isinstance(data, dict) or data.get("version") != CACHE_VERSION:
        return None, "Dashboard cache is missing or from an older version."
    snapshot = data.get("snapshot")
    if not isinstance(snapshot, dict):
        return None, "Dashboard cache did not contain a valid snapshot."
    return data, None


def save_dashboard_cache(project_root: str | Path, snapshot: dict[str, Any]) -> Path:
    path = dashboard_cache_path(project_root)
    ensure_directory(path.parent)
    payload = {
        "version": CACHE_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "project_root": str(project_root),
        "source_metadata": source_metadata(project_root),
        "snapshot": snapshot,
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
    return path


def cache_is_stale(project_root: str | Path, cache_payload: dict[str, Any]) -> bool:
    return cache_payload.get("source_metadata") != source_metadata(project_root)


def cached_snapshot(project_root: str | Path) -> tuple[dict[str, Any] | None, bool, str | None]:
    payload, warning = load_dashboard_cache(project_root)
    if payload is None:
        return None, True, warning
    return payload["snapshot"], cache_is_stale(project_root, payload), None
