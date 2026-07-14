from __future__ import annotations

import json
import atexit
import queue
import threading
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


_LOG_QUEUE: queue.Queue[dict] = queue.Queue()
_LOG_THREAD: threading.Thread | None = None
_LOG_THREAD_LOCK = threading.Lock()
_LOG_SENTINEL = {"stop": True}


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


LIBRARY_PERFORMANCE_TARGETS_SECONDS = {
    "library.open": 0.5,
    "library.render.visible_cards": 0.25,
    "library.interaction.category_switch": 0.3,
    "library.interaction.search_execute": 0.2,
    "library.interaction.filter_execute": 0.3,
    "library.interaction.sort_execute": 0.3,
    "library.interaction.pagination_execute": 0.2,
    "record.open.eoat": 0.5,
    "record.open.tool": 0.5,
    "record.open.machine": 0.5,
    "record.relationship_render": 0.15,
    "record.render.details_tab_lazy": 0.4,
    "record.render.photos_tab_lazy": 0.5,
}


def performance_log_path(project_root: str | Path) -> Path:
    root = Path(project_root)
    if root.name in {"EOAT_Atlas_Dev", "EOAT_Atlas"}:
        return root / "logs" / "performance.log"
    return resolve_project_paths(project_root).logs / "performance.log"


def performance_jsonl_path(project_root: str | Path) -> Path:
    root = Path(project_root)
    if root.name in {"EOAT_Atlas_Dev", "EOAT_Atlas"}:
        return root / "logs" / "performance.jsonl"
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
        if not str(project_root).strip():
            return "Performance logging skipped because project root is empty."
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
            handle.write(json.dumps(event, default=str, ensure_ascii=True, sort_keys=True) + "\n")
    except Exception as exc:
        return f"Structured performance logging failed: {exc}"
    return None


def _write_performance_event(project_root: str | Path, event: dict) -> str | None:
    try:
        if not str(project_root).strip():
            return "Performance logging skipped because project root is empty."
        if not Path(project_root).exists():
            return f"Performance logging skipped because project root does not exist: {project_root}"
        path = performance_jsonl_path(project_root)
        ensure_directory(path.parent)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, default=str, ensure_ascii=True, sort_keys=True) + "\n")
    except Exception as exc:
        return f"Structured performance logging failed: {exc}"
    return None


def _performance_event_payload(
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
    project_root_mode: str | None = None,
) -> dict:
    if project_root_mode is None:
        try:
            mode = project_data_mode(project_root)
        except Exception:
            mode = "unknown"
    else:
        mode = project_root_mode
    return {
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


def _ensure_log_worker() -> None:
    global _LOG_THREAD
    with _LOG_THREAD_LOCK:
        if _LOG_THREAD is not None and _LOG_THREAD.is_alive():
            return
        _LOG_THREAD = threading.Thread(target=_log_worker, name="PerformanceLogWriter", daemon=True)
        _LOG_THREAD.start()


def _log_worker() -> None:
    while True:
        item = _LOG_QUEUE.get()
        batch = [item]
        try:
            if item is _LOG_SENTINEL or item.get("stop"):
                return
            while len(batch) < 100:
                try:
                    next_item = _LOG_QUEUE.get_nowait()
                except queue.Empty:
                    break
                if next_item is _LOG_SENTINEL or next_item.get("stop"):
                    _LOG_QUEUE.task_done()
                    return
                batch.append(next_item)
            _write_queued_log_batch(batch)
        finally:
            for _ in batch:
                _LOG_QUEUE.task_done()


def _write_queued_log_item(item: dict) -> None:
    _write_queued_log_batch([item])


def _write_queued_log_batch(items: list[dict]) -> None:
    grouped: dict[str, list[dict]] = {}
    roots: dict[str, str | Path] = {}
    for item in items:
        project_root = item.get("project_root", "")
        root_key = str(project_root)
        if not root_key.strip():
            continue
        grouped.setdefault(root_key, []).append(item)
        roots[root_key] = project_root
    for root_key, root_items in grouped.items():
        project_root = roots[root_key]
        _write_queued_log_group(project_root, root_items)


def _write_queued_log_group(project_root: str | Path, items: list[dict]) -> None:
    try:
        if not str(project_root).strip() or not Path(project_root).exists():
            return
        text_path = performance_log_path(project_root)
        ensure_directory(text_path.parent)
        with text_path.open("a", encoding="utf-8") as handle:
            handle.write("".join(str(item.get("text_line", "")) for item in items))
        jsonl_path = performance_jsonl_path(project_root)
        ensure_directory(jsonl_path.parent)
        try:
            mode = project_data_mode(project_root)
        except Exception:
            mode = "unknown"
        lines = []
        for item in items:
            event = _performance_event_payload(
                project_root,
                item["operation"],
                item["elapsed_seconds"],
                success=item["success"],
                source=item["source"],
                page_tool=item["page_tool"],
                details=item["details"],
                warning_count=item["warning_count"],
                error_count=item["error_count"],
                project_root_mode=mode,
            )
            lines.append(json.dumps(event, default=str, ensure_ascii=True, sort_keys=True) + "\n")
        with jsonl_path.open("a", encoding="utf-8") as handle:
            handle.write("".join(lines))
    except Exception:
        return


def flush_performance_log_queue(timeout: float = 10.0) -> None:
    deadline = time.perf_counter() + max(0.0, float(timeout))
    while time.perf_counter() < deadline:
        if _LOG_QUEUE.unfinished_tasks == 0:
            return
        time.sleep(0.01)


def _flush_performance_log_queue_at_exit() -> None:
    flush_performance_log_queue(timeout=2.0)


atexit.register(_flush_performance_log_queue_at_exit)


def log_performance(
    project_root: str | Path,
    operation: str,
    elapsed_seconds: float,
    details: str | dict | list = "",
    *,
    success: bool = True,
    source: str = "",
    page_tool: str = "",
    warning_count: int = 0,
    error_count: int = 0,
) -> str | None:
    warnings: list[str] = []
    if isinstance(details, str):
        detail_text = details.strip()
    else:
        detail_text = json.dumps(details, default=str, ensure_ascii=True, sort_keys=True)
    suffix = f" {detail_text}" if detail_text else ""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    elapsed_ms = float(elapsed_seconds) * 1000
    text_line = f"[{timestamp}] [PERF] {operation}: {elapsed_ms:.1f} ms ({elapsed_seconds:.2f}s){suffix}\n"

    if isinstance(details, dict) and details.get("qt_ui_thread"):
        try:
            if not str(project_root).strip():
                return "Performance logging skipped because project root is empty."
            _ensure_log_worker()
            _LOG_QUEUE.put(
                {
                    "project_root": project_root,
                    "operation": operation,
                    "elapsed_seconds": elapsed_seconds,
                    "text_line": text_line,
                    "success": success,
                    "source": source,
                    "page_tool": page_tool,
                    "details": details,
                    "warning_count": warning_count,
                    "error_count": error_count,
                }
            )
            return None
        except Exception as exc:
            warnings.append(f"Async performance logging failed: {exc}")

    try:
        if not str(project_root).strip():
            return "Performance logging skipped because project root is empty."
        if not Path(project_root).exists():
            return f"Performance logging skipped because project root does not exist: {project_root}"
        path = performance_log_path(project_root)
        ensure_directory(path.parent)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(text_line)
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


def perf_thread_context() -> dict[str, object]:
    """Return thread context for performance logs without forcing Qt at import time."""
    current = threading.current_thread()
    details: dict[str, object] = {
        "thread_name": current.name,
        "thread_id": current.ident,
        "python_main_thread": current is threading.main_thread(),
        "qt_app": False,
        "qt_ui_thread": False,
    }
    try:
        from PySide6.QtCore import QCoreApplication, QThread

        app = QCoreApplication.instance()
        details["qt_app"] = app is not None
        details["qt_ui_thread"] = bool(app is not None and QThread.currentThread() == app.thread())
    except Exception:
        details["qt_thread_check_error"] = True
    return details


def _perf_details(details: str | dict | list | None, *, include_thread: bool) -> str | dict | list:
    if include_thread:
        thread_details = perf_thread_context()
        if isinstance(details, dict):
            merged = {**details, **thread_details}
            if merged.get("ui_sensitive") and merged.get("qt_ui_thread"):
                merged["ui_thread_warning"] = f"{merged['ui_sensitive']}_on_ui_thread"
            return merged
        if details:
            merged = {"detail": details, **thread_details}
            return merged
        return thread_details
    return details or ""


@contextmanager
def perf_timer(
    project_root: str | Path,
    operation: str,
    details: str | dict | list | None = None,
    *,
    source: str = "",
    page_tool: str = "",
    include_thread: bool = True,
) -> Iterator[None]:
    """Small reusable performance timer that writes readable ms logs and JSONL events."""
    started = time.perf_counter()
    success = True
    error = ""
    try:
        yield
    except Exception as exc:
        success = False
        error = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        payload = _perf_details(details, include_thread=include_thread)
        if error:
            if isinstance(payload, dict):
                payload = {**payload, "error": error}
            else:
                payload = {"detail": payload, "error": error}
        log_performance(
            project_root,
            operation,
            time.perf_counter() - started,
            details=payload,
            success=success,
            source=source,
            page_tool=page_tool,
        )


def log_perf_marker(
    project_root: str | Path,
    operation: str,
    details: str | dict | list | None = None,
    *,
    source: str = "",
    page_tool: str = "",
    include_thread: bool = True,
) -> str | None:
    return log_performance(
        project_root,
        operation,
        0.0,
        details=_perf_details(details, include_thread=include_thread),
        source=source,
        page_tool=page_tool,
    )


def read_recent_performance_events(project_root: str | Path, limit: int = 200) -> tuple[list[dict], str | None]:
    flush_performance_log_queue()
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


def summarize_library_performance(events: list[dict]) -> dict:
    """Return a pass/fail Library optimization summary from performance events."""
    metrics: dict[str, dict] = {}
    for operation, target_seconds in LIBRARY_PERFORMANCE_TARGETS_SECONDS.items():
        values = [_duration(event) for event in events if str(event.get("operation") or "") == operation]
        if not values:
            metrics[operation] = {
                "count": 0,
                "max_ms": None,
                "target_ms": round(target_seconds * 1000, 1),
                "pass": None,
            }
            continue
        max_seconds = max(values)
        metrics[operation] = {
            "count": len(values),
            "avg_ms": round((sum(values) / len(values)) * 1000, 3),
            "max_ms": round(max_seconds * 1000, 3),
            "target_ms": round(target_seconds * 1000, 1),
            "pass": max_seconds <= target_seconds,
        }

    warning_counts = _library_warning_counts(events)
    thumbnail_hits = sum(1 for event in events if str(event.get("operation") or "") in {"photo_service.memory_cache_hit", "photo_service.disk_cache_hit"})
    thumbnail_requests = sum(1 for event in events if str(event.get("operation") or "") == "photo_service.request_thumbnail")
    measured = [item for item in metrics.values() if item["pass"] is not None]
    return {
        "status": "PASS" if all(item["pass"] for item in measured) and not any(warning_counts.values()) else "FAIL",
        "metrics": metrics,
        "warnings": warning_counts,
        "thumbnail_cache_hit_rate": round(thumbnail_hits / thumbnail_requests, 4) if thumbnail_requests else None,
    }


def _library_warning_counts(events: list[dict]) -> dict[str, int]:
    counts = {
        "excel_read_on_ui_thread": 0,
        "photo_path_resolution_on_ui_thread": 0,
        "image_decode_on_ui_thread": 0,
        "thumbnail_decode_on_ui_thread": 0,
    }
    for event in events:
        details = event.get("details")
        detail_text = json.dumps(details, default=str, ensure_ascii=True).casefold() if not isinstance(details, str) else details.casefold()
        for warning in counts:
            if warning in detail_text:
                counts[warning] += 1
    return counts


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
    "log_perf_marker",
    "perf_thread_context",
    "perf_timer",
    "performance_jsonl_path",
    "performance_log_path",
    "read_recent_performance_events",
    "summarize_library_performance",
    "summarize_performance",
    "timed_operation",
]
