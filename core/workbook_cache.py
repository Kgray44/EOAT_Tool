from __future__ import annotations

import copy
import time
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any

from .performance import log_performance, perf_thread_context
from .workbook_io import row_dicts, workbook_sheet_names


@dataclass(frozen=True)
class WorkbookFileSignature:
    path: str
    exists: bool
    mtime_ns: int
    size: int


@dataclass(frozen=True)
class WorkbookCacheKey:
    path: str
    sheet_name: str
    mtime_ns: int
    size: int
    data_only: bool


_ROW_CACHE: dict[WorkbookCacheKey, tuple[dict[str, Any], ...]] = {}
_SHEET_NAMES_CACHE: dict[tuple[str, int, int], tuple[str, ...]] = {}
_LOCK = RLock()


def workbook_file_signature(path: str | Path) -> WorkbookFileSignature:
    target = Path(path).expanduser().resolve()
    try:
        stat = target.stat()
    except OSError:
        return WorkbookFileSignature(path=str(target), exists=False, mtime_ns=0, size=0)
    return WorkbookFileSignature(path=str(target), exists=True, mtime_ns=stat.st_mtime_ns, size=stat.st_size)


def row_dicts_cached(workbook_path: str | Path, sheet_name: str, data_only: bool = True) -> list[dict[str, Any]]:
    signature = workbook_file_signature(workbook_path)
    key = WorkbookCacheKey(signature.path, str(sheet_name), signature.mtime_ns, signature.size, bool(data_only))
    started = time.perf_counter()
    with _LOCK:
        cached = _ROW_CACHE.get(key)
        if cached is not None:
            _log_cache_event(
                workbook_path, "workbook_cache.hit", started, sheet_name=sheet_name, cache_type="row_dicts"
            )
            return [dict(row) for row in cached]
    rows = row_dicts(workbook_path, sheet_name)
    snapshot = tuple(copy.deepcopy(row) for row in rows)
    with _LOCK:
        _ROW_CACHE[key] = snapshot
    _log_cache_event(workbook_path, "workbook_cache.miss", started, sheet_name=sheet_name, cache_type="row_dicts")
    return [dict(row) for row in snapshot]


def workbook_sheet_names_cached(workbook_path: str | Path) -> list[str]:
    signature = workbook_file_signature(workbook_path)
    key = (signature.path, signature.mtime_ns, signature.size)
    started = time.perf_counter()
    with _LOCK:
        cached = _SHEET_NAMES_CACHE.get(key)
        if cached is not None:
            _log_cache_event(workbook_path, "workbook_cache.hit", started, cache_type="sheet_names")
            return list(cached)
    names = workbook_sheet_names(workbook_path)
    with _LOCK:
        _SHEET_NAMES_CACHE[key] = tuple(names)
    _log_cache_event(workbook_path, "workbook_cache.miss", started, cache_type="sheet_names")
    return list(names)


def invalidate_workbook_cache(path: str | Path | None = None) -> None:
    started = time.perf_counter()
    if path is None:
        invalidate_all_workbook_cache()
        return
    signature = workbook_file_signature(path)
    target = signature.path
    with _LOCK:
        for key in list(_ROW_CACHE):
            if key.path == target:
                _ROW_CACHE.pop(key, None)
        for key in list(_SHEET_NAMES_CACHE):
            if key[0] == target:
                _SHEET_NAMES_CACHE.pop(key, None)
    _log_cache_event(path, "workbook_cache.invalidate", started, cache_type="path")


def invalidate_all_workbook_cache() -> None:
    with _LOCK:
        _ROW_CACHE.clear()
        _SHEET_NAMES_CACHE.clear()


def _log_cache_event(path: str | Path, operation: str, started: float, **details: Any) -> None:
    project_root = _project_root_for_path(Path(path))
    if project_root is None:
        return
    payload = {
        "ui_sensitive": "cached_data_load",
        "workbook": str(Path(path).name),
        "cache_status": operation.rsplit(".", 1)[-1],
        **details,
        **perf_thread_context(),
    }
    if payload.get("qt_ui_thread"):
        payload["ui_thread_warning"] = "cached_data_load_on_ui_thread"
    log_performance(
        project_root,
        operation,
        time.perf_counter() - started,
        source="workbook_cache",
        page_tool="cache",
        details=payload,
    )


def _project_root_for_path(path: Path) -> Path | None:
    try:
        resolved = path.expanduser().resolve()
    except OSError:
        resolved = path
    for parent in [resolved.parent, *resolved.parents]:
        if (parent / "00_Project_Admin").exists():
            return parent
    return None


__all__ = [
    "WorkbookCacheKey",
    "WorkbookFileSignature",
    "invalidate_all_workbook_cache",
    "invalidate_workbook_cache",
    "row_dicts_cached",
    "workbook_file_signature",
    "workbook_sheet_names_cached",
]
