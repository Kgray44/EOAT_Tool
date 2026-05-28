from __future__ import annotations

import json
import time
from contextlib import contextmanager
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from .paths import resolve_project_paths
from .project_root_status import project_data_mode
from .safe_files import ensure_directory


def performance_log_path(project_root: str | Path) -> Path:
    return resolve_project_paths(project_root).logs / "performance.log"


def performance_jsonl_path(project_root: str | Path) -> Path:
    return resolve_project_paths(project_root).logs / "performance.jsonl"


def log_performance_event(
    project_root: str | Path,
    operation: str,
    duration_seconds: float,
    *,
    success: bool = True,
    source: str = "",
    page_tool: str = "",
    details: str | dict | list = "",
    warning_count: int = 0,
    error_count: int = 0,
) -> str | None:
    try:
        if not Path(project_root).exists():
            return f"Performance logging skipped because project root does not exist: {project_root}"
        path = performance_jsonl_path(project_root)
        ensure_directory(path.parent)
        try:
            mode = project_data_mode(project_root)
        except Exception:
            mode = "unknown"
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "operation": str(operation),
            "duration_seconds": round(float(duration_seconds), 4),
            "success": bool(success),
            "source": str(source or ""),
            "page_tool": str(page_tool or ""),
            "project_root_mode": mode,
            "details": details,
            "warning_count": int(warning_count or 0),
            "error_count": int(error_count or 0),
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=True, sort_keys=True) + "\n")
    except Exception as exc:
        return f"Structured performance logging failed: {exc}"
    return None


def log_performance(
    project_root: str | Path,
    operation: str,
    elapsed_seconds: float,
    details: str = "",
    *,
    success: bool = True,
    source: str = "",
    page_tool: str = "",
    warning_count: int = 0,
    error_count: int = 0,
) -> str | None:
    warnings: list[str] = []
    try:
        if not Path(project_root).exists():
            return f"Performance logging skipped because project root does not exist: {project_root}"
        path = performance_log_path(project_root)
        ensure_directory(path.parent)
        if isinstance(details, str):
            detail_text = details.strip()
        else:
            detail_text = json.dumps(details, ensure_ascii=True, sort_keys=True)
        suffix = f" {detail_text}" if detail_text else ""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"[{timestamp}] [PERF] {operation}: {elapsed_seconds:.2f}s{suffix}\n")
    except Exception as exc:
        warnings.append(f"Performance logging failed: {exc}")
    structured_warning = log_performance_event(
        project_root,
        operation,
        elapsed_seconds,
        success=success,
        source=source,
        page_tool=page_tool,
        details=details,
        warning_count=warning_count,
        error_count=error_count,
    )
    if structured_warning:
        warnings.append(structured_warning)
    return "; ".join(warnings) if warnings else None


def read_recent_performance_events(project_root: str | Path, limit: int = 200) -> tuple[list[dict], str | None]:
    path = performance_jsonl_path(project_root)
    if not path.exists():
        return [], None
    try:
        with path.open("r", encoding="utf-8") as handle:
            lines = deque((line.rstrip("\n") for line in handle if line.strip()), maxlen=max(1, int(limit)))
    except OSError as exc:
        return [], f"Could not read performance log: {exc}"
    events: list[dict] = []
    warning: str | None = None
    for line in list(lines):
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            warning = "Some performance log lines could not be parsed."
            continue
        if isinstance(parsed, dict):
            events.append(parsed)
    events.reverse()
    return events, warning


def summarize_performance(events: list[dict], *, slow_limit: int = 10) -> dict:
    def duration(event: dict) -> float:
        try:
            return float(event.get("duration_seconds") or 0)
        except (TypeError, ValueError):
            return 0.0

    by_operation: dict[str, list[float]] = {}
    cache_hits = 0
    cache_misses = 0
    cache_stale = 0
    warning_count = 0
    error_count = 0
    for event in events:
        operation = str(event.get("operation") or "unknown")
        by_operation.setdefault(operation, []).append(duration(event))
        warning_count += int(event.get("warning_count") or 0)
        error_count += int(event.get("error_count") or 0)
        details = event.get("details")
        if isinstance(details, dict):
            cache_status = str(details.get("cache_status") or "").casefold()
            if cache_status == "hit":
                cache_hits += 1
            elif cache_status == "miss":
                cache_misses += 1
            elif cache_status == "stale":
                cache_stale += 1
        elif isinstance(details, str):
            lowered = details.casefold()
            if "cache_status=hit" in lowered:
                cache_hits += 1
            elif "cache_status=miss" in lowered:
                cache_misses += 1
            elif "stale_cache=true" in lowered or "cache_status=stale" in lowered:
                cache_stale += 1

    slowest = sorted(events, key=duration, reverse=True)[:slow_limit]
    operation_summary = [
        {
            "operation": operation,
            "count": len(values),
            "avg_duration_seconds": round(sum(values) / len(values), 4),
            "p50_duration_seconds": round(_percentile(values, 50), 4),
            "p95_duration_seconds": round(_percentile(values, 95), 4),
            "max_duration_seconds": round(max(values), 4),
        }
        for operation, values in sorted(by_operation.items())
        if values
    ]
    operation_summary.sort(key=lambda item: item["max_duration_seconds"], reverse=True)
    latest_by_prefix = {
        "startup": _latest_event(events, "app_start."),
        "dashboard_quick_refresh": _latest_event(events, "dashboard.quick_refresh"),
        "dashboard_deep_refresh": _latest_event(events, "dashboard.deep_refresh"),
        "audit_save": _latest_operation_contains(events, ("audit", "save")),
        "validation": _latest_operation_contains(events, ("validation",)),
        "report_generation": _latest_report_event(events),
    }
    return {
        "event_count": len(events),
        "slowest_operations": slowest,
        "operation_summary": operation_summary,
        "latest": latest_by_prefix,
        "cache": {"hit": cache_hits, "miss": cache_misses, "stale": cache_stale},
        "warning_count": warning_count,
        "error_count": error_count,
    }


def _latest_event(events: list[dict], prefix: str) -> dict | None:
    for event in events:
        if str(event.get("operation") or "").startswith(prefix):
            return event
    return None


def _percentile(values: list[float], percentile: int) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * (percentile / 100)
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    weight = rank - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _latest_operation_contains(events: list[dict], words: tuple[str, ...]) -> dict | None:
    for event in events:
        operation = str(event.get("operation") or "").casefold()
        if all(word in operation for word in words):
            return event
    return None


def _latest_report_event(events: list[dict]) -> dict | None:
    for event in events:
        operation = str(event.get("operation") or "")
        if "report" in operation or "summary" in operation:
            return event
    return None


@contextmanager
def timed_operation(project_root: str | Path, operation: str, details: str = "") -> Iterator[None]:
    started = time.perf_counter()
    try:
        yield
    finally:
        log_performance(project_root, operation, time.perf_counter() - started, details)


__all__ = [
    "log_performance",
    "log_performance_event",
    "performance_jsonl_path",
    "performance_log_path",
    "read_recent_performance_events",
    "summarize_performance",
    "timed_operation",
]
