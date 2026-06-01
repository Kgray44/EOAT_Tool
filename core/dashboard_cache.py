from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .paths import resolve_project_paths
from .safe_files import ensure_directory
from .scheduled_reports import scheduled_tools_log_path

CACHE_VERSION = 2


@dataclass(frozen=True)
class CacheStatus:
    snapshot: dict[str, Any] | None
    stale: bool
    warning: str | None = None
    stale_reasons: list[str] = field(default_factory=list)
    cache_hit: bool = False

    @property
    def stale_explanation(self) -> str:
        if self.warning:
            return self.warning
        if not self.stale:
            return "Dashboard cache is fresh."
        if not self.stale_reasons:
            return "Dashboard cache is stale."
        return "Dashboard cache stale because:\n" + "\n".join(f"- {reason}" for reason in self.stale_reasons)


def dashboard_cache_path(project_root: str | Path) -> Path:
    return resolve_project_paths(project_root).cache / "dashboard_snapshot.json"


def _file_signature(path: Path) -> dict[str, Any]:
    try:
        stat = path.stat()
    except OSError:
        return {"path": str(path), "exists": False, "mtime_ns": None, "size": None}
    return {"path": str(path), "exists": True, "mtime_ns": stat.st_mtime_ns, "size": stat.st_size}


def _source_file(key: str, label: str, path: Path, *, optional: bool = True) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "kind": "file",
        "optional": optional,
        **_file_signature(path),
    }


def _source_file_group(key: str, label: str, files: list[Path], *, optional: bool = True) -> dict[str, Any]:
    unique = sorted(set(files), key=lambda item: str(item).casefold())
    metadata = [_file_signature(path) for path in unique if path.exists() and path.is_file()]
    latest_mtime = max((item["mtime_ns"] or 0 for item in metadata), default=None)
    total_size = sum(int(item["size"] or 0) for item in metadata)
    return {
        "key": key,
        "label": label,
        "kind": "file_group",
        "optional": optional,
        "exists": bool(metadata),
        "path": "",
        "file_count": len(metadata),
        "latest_mtime_ns": latest_mtime,
        "total_size": total_size,
        "files": metadata,
    }


def _source_folder(
    key: str, label: str, folder: Path, *, patterns: tuple[str, ...] = ("*",), optional: bool = True
) -> dict[str, Any]:
    files: list[Path] = []
    if folder.exists():
        for pattern in patterns:
            files.extend(path for path in folder.glob(pattern) if path.is_file())
    source = _source_file_group(key, label, files, optional=optional)
    source["kind"] = "folder"
    source["path"] = str(folder)
    source["folder_exists"] = folder.exists()
    return source


def _project_admin_files(paths, *patterns: str) -> list[Path]:
    if not paths.project_admin.exists():
        return []
    files: list[Path] = []
    for pattern in patterns:
        files.extend(path for path in paths.project_admin.glob(pattern) if path.is_file())
    return files


def _photo_index_files(paths) -> list[Path]:
    candidates: list[Path] = []
    for folder in [paths.audit_root, paths.cell_photos, paths.project_admin]:
        if not folder.exists():
            continue
        for pattern in ("Photo_Index*.*", "*Photo*Index*.csv", "*Photo*Index*.xlsx", "*photo*index*.json"):
            candidates.extend(path for path in folder.glob(pattern) if path.is_file())
    return candidates


def source_metadata(project_root: str | Path) -> dict[str, Any]:
    paths = resolve_project_paths(project_root)
    sources = [
        _source_file("master_tracker_workbook", "EOAT_Master_Tracker.xlsx", paths.master_workbook, optional=False),
        _source_file("activity_log", "activity_log.jsonl", paths.activity_logs / "activity_log.jsonl"),
        _source_file("scheduled_report_log", "scheduled_tools.log", scheduled_tools_log_path(project_root)),
        _source_folder(
            "daily_report_folder", "Daily status reports folder", paths.daily_reports, patterns=("*.md", "*.json")
        ),
        _source_folder(
            "weekly_report_folder", "Weekly status reports folder", paths.weekly_reports, patterns=("*.md", "*.json")
        ),
        _source_file_group(
            "task_schedule_files",
            "Project schedule/task files",
            _project_admin_files(paths, "project_schedule_week*.json", "task_progress_week*.json"),
        ),
        _source_file("annotation_database", "annotations.sqlite", paths.annotations_database),
        _source_file("robot_info_workbook", "Robot_Info.xlsx", paths.robot_info_workbook),
        _source_file_group(
            "validation_findings_json",
            "Validation findings JSON",
            [
                path
                for path in paths.validation_reports.glob("Foundation_Validation_*.json")
                if paths.validation_reports.exists()
            ],
        ),
        _source_file_group("photo_index_files", "Photo index files", _photo_index_files(paths)),
        _source_folder(
            "documentation_gap_outputs",
            "Documentation gap outputs",
            paths.documentation_gap_reports,
            patterns=("*.md", "*.csv", "*.json"),
        ),
        _source_file_group(
            "open_items_outputs",
            "Open items outputs",
            [path for path in paths.annotation_exports.glob("open_items_report*") if paths.annotation_exports.exists()],
        ),
    ]
    return {
        "schema": "dashboard_cache_sources_v2",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sources": sources,
    }


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


def stale_reasons(project_root: str | Path, cache_payload: dict[str, Any]) -> list[str]:
    old_metadata = cache_payload.get("source_metadata")
    if not isinstance(old_metadata, dict) or "sources" not in old_metadata:
        return ["Cache was created before expanded source tracking."]
    old_sources = _source_map(old_metadata)
    current_sources = _source_map(source_metadata(project_root))
    reasons: list[str] = []
    for key in sorted(set(old_sources) | set(current_sources)):
        old = old_sources.get(key)
        current = current_sources.get(key)
        if old is None and current is not None:
            reasons.append(f"{current.get('label', key)} is now tracked.")
            continue
        if current is None and old is not None:
            reasons.append(f"{old.get('label', key)} is no longer tracked.")
            continue
        if old is None or current is None:
            continue
        if _source_comparison_payload(old) != _source_comparison_payload(current):
            reasons.append(_source_change_reason(old, current))
    return reasons


def cache_is_stale(project_root: str | Path, cache_payload: dict[str, Any]) -> bool:
    return bool(stale_reasons(project_root, cache_payload))


def cached_snapshot_status(project_root: str | Path) -> CacheStatus:
    payload, warning = load_dashboard_cache(project_root)
    if payload is None:
        return CacheStatus(None, True, warning=warning, stale_reasons=[warning] if warning else [], cache_hit=False)
    reasons = stale_reasons(project_root, payload)
    return CacheStatus(payload["snapshot"], bool(reasons), stale_reasons=reasons, cache_hit=True)


def cached_snapshot(project_root: str | Path) -> tuple[dict[str, Any] | None, bool, str | None]:
    status = cached_snapshot_status(project_root)
    return status.snapshot, status.stale, status.warning


def _source_map(metadata: dict[str, Any]) -> dict[str, dict[str, Any]]:
    sources = metadata.get("sources")
    if not isinstance(sources, list):
        return {}
    mapped: dict[str, dict[str, Any]] = {}
    for source in sources:
        if isinstance(source, dict) and source.get("key"):
            mapped[str(source["key"])] = source
    return mapped


def _source_comparison_payload(source: dict[str, Any]) -> dict[str, Any]:
    keys = ["exists", "mtime_ns", "size", "file_count", "latest_mtime_ns", "total_size", "folder_exists"]
    payload = {key: source.get(key) for key in keys if key in source}
    files = source.get("files")
    if isinstance(files, list):
        payload["files"] = [
            {key: file_meta.get(key) for key in ["path", "exists", "mtime_ns", "size"]}
            for file_meta in files
            if isinstance(file_meta, dict)
        ]
    return payload


def _source_change_reason(old: dict[str, Any], current: dict[str, Any]) -> str:
    label = str(current.get("label") or old.get("label") or current.get("key") or "Cache source")
    old_exists = bool(old.get("exists"))
    current_exists = bool(current.get("exists"))
    if old_exists != current_exists:
        return f"{label} {'appeared' if current_exists else 'is missing'}."
    old_count = old.get("file_count")
    current_count = current.get("file_count")
    if old_count != current_count:
        return f"{label} file count changed from {old_count or 0} to {current_count or 0}."
    return f"{label} changed."


__all__ = [
    "CacheStatus",
    "cache_is_stale",
    "cached_snapshot",
    "cached_snapshot_status",
    "dashboard_cache_path",
    "load_dashboard_cache",
    "save_dashboard_cache",
    "source_metadata",
    "stale_reasons",
]
