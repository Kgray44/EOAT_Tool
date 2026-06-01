from __future__ import annotations

import json
import time
from collections import deque
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .paths import resolve_project_paths
from .project_root_status import project_data_mode
from .safe_files import ensure_directory


@dataclass(frozen=True)
class PerformanceDoctorFinding:
    operation: str
    duration_seconds: float
    likely_cause: str
    recommendation: str
    severity: str = "info"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class PerformanceDoctorSummary:
    event_count: int
    slowest_operation: str
    slowest_duration_seconds: float
    findings: tuple[PerformanceDoctorFinding, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "event_count": self.event_count,
            "slowest_operation": self.slowest_operation,
            "slowest_duration_seconds": self.slowest_duration_seconds,
            "findings": [finding.to_dict() for finding in self.findings],
        }


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


def analyze_performance_doctor(
    project_root: str | Path, *, limit: int = 500
) -> tuple[PerformanceDoctorSummary, str | None]:
    events, warning = read_recent_performance_events(project_root, limit=limit)
    findings = tuple(
        _doctor_finding(event)
        for event in sorted(events, key=_duration, reverse=True)[:20]
        if _duration(event) >= _slow_threshold(event)
    )
    slowest = max(events, key=_duration, default={})
    return (
        PerformanceDoctorSummary(
            event_count=len(events),
            slowest_operation=str(slowest.get("operation") or ""),
            slowest_duration_seconds=round(_duration(slowest), 4),
            findings=findings,
        ),
        warning,
    )


def _doctor_finding(event: dict) -> PerformanceDoctorFinding:
    operation = str(event.get("operation") or "unknown")
    duration = round(_duration(event), 4)
    lowered = operation.casefold()
    details = event.get("details")
    detail_text = (
        json.dumps(details, ensure_ascii=True).casefold() if not isinstance(details, str) else details.casefold()
    )
    if "lock" in lowered:
        cause = "Workbook lock wait was recorded."
        recommendation = "Close Excel/Office lock files before save, repair, or migration operations."
    elif "startup" in lowered or "load_config" in lowered or "config" in lowered:
        cause = "Startup/config loading is taking longer than expected."
        recommendation = "Check network project root latency and avoid heavy work before the main window appears."
    elif "page" in lowered and ("create" in lowered or "constructor" in lowered):
        cause = "Page creation may be doing expensive work in the constructor."
        recommendation = "Move workbook reads and scans into background refresh/on-show paths."
    elif "workbook" in lowered and ("open" in lowered or "save" in lowered):
        cause = "Workbook IO is slow, possibly due to network storage, file size, or Excel locks."
        recommendation = "Use cached reads where safe, close Excel before saves, and keep workbook writes batched."
    elif "validation" in lowered:
        cause = "Validation scan is expensive."
        recommendation = "Run full validation on demand, cache summaries, and avoid triggering validation on page open."
    elif "report" in lowered or "summary" in lowered:
        cause = "Report generation is one of the slower operations."
        recommendation = "Generate reports in background and reuse existing summaries when inputs have not changed."
    elif "cache" in lowered or "cache_status" in detail_text:
        cause = "Cache read/write or stale-cache handling is visible in timing."
        recommendation = "Review cache hit rate and invalidate only affected caches."
    elif "event" in lowered or "dispatch" in lowered:
        cause = "Event dispatch or page refresh listeners may be doing too much work."
        recommendation = "Keep event handlers lightweight and mark heavy pages stale instead of refreshing immediately."
    elif "queue" in lowered or "background" in lowered:
        cause = "Background queue wait time is elevated."
        recommendation = "Avoid starting duplicate long-running workbook tasks and surface queue status to users."
    else:
        cause = "Operation duration is above the diagnostic threshold."
        recommendation = "Inspect operation details and add finer-grained timing around this workflow."
    severity = "warning" if duration >= 5 else "info"
    return PerformanceDoctorFinding(
        operation=operation,
        duration_seconds=duration,
        likely_cause=cause,
        recommendation=recommendation,
        severity=severity,
    )


def _duration(event: dict) -> float:
    try:
        return float(event.get("duration_seconds") or 0)
    except (TypeError, ValueError):
        return 0.0


def _slow_threshold(event: dict) -> float:
    operation = str(event.get("operation") or "").casefold()
    if "lock" in operation:
        return 0.25
    if "startup" in operation or "config" in operation or "cache" in operation or "event" in operation:
        return 0.5
    if "page" in operation and ("create" in operation or "constructor" in operation):
        return 0.75
    if "workbook" in operation or "validation" in operation or "report" in operation:
        return 1.0
    if "queue" in operation:
        return 0.25
    return 2.0


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
    "PerformanceDoctorFinding",
    "PerformanceDoctorSummary",
    "analyze_performance_doctor",
    "log_performance",
    "log_performance_event",
    "performance_jsonl_path",
    "performance_log_path",
    "read_recent_performance_events",
    "summarize_performance",
    "timed_operation",
]
