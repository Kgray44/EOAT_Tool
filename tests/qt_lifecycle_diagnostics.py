"""Opt-in Qt lifecycle snapshots for same-process test diagnostics.

Set ``EOAT_QT_LIFECYCLE_DIAGNOSTICS=1`` and optionally
``EOAT_QT_LIFECYCLE_TRACE=<path>`` to write compact JSONL snapshots.  This is
test-only instrumentation: it neither creates a QApplication nor drains
events, so it cannot conceal a lifetime defect.
"""

from __future__ import annotations

import gc
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def diagnostics_enabled() -> bool:
    return os.getenv("EOAT_QT_LIFECYCLE_DIAGNOSTICS", "").strip().casefold() in {"1", "true", "yes"}


def deep_diagnostics_enabled() -> bool:
    return os.getenv("EOAT_QT_LIFECYCLE_DEEP", "").strip().casefold() in {"1", "true", "yes"}


def cleanup_assertions_enabled() -> bool:
    """Opt in to strict post-teardown checks for Qt-heavy test runs."""
    return os.getenv("EOAT_QT_LIFECYCLE_ASSERT_CLEAN", "").strip().casefold() in {"1", "true", "yes"}


def _is_valid(value: object) -> bool:
    try:
        from shiboken6 import isValid

        return bool(isValid(value))
    except (ImportError, RuntimeError, TypeError):
        return False


def _object_description(value: object) -> dict[str, Any]:
    description: dict[str, Any] = {"class": type(value).__name__, "valid": _is_valid(value)}
    if not description["valid"]:
        return description
    try:
        description["object_name"] = value.objectName()  # type: ignore[attr-defined]
    except RuntimeError:
        description["valid"] = False
    return description


def _live_python_objects(class_names: set[str]) -> tuple[int, int]:
    """Return live and invalid wrappers without calling invalid wrapper methods."""
    live = 0
    invalid = 0
    for value in gc.get_objects():
        if type(value).__name__ not in class_names:
            continue
        if _is_valid(value):
            live += 1
        else:
            invalid += 1
    return live, invalid


def _invalid_wrapper_descriptions(class_names: set[str], *, limit: int = 12) -> list[dict[str, Any]]:
    """Describe stale wrappers without invoking methods on invalid objects."""
    descriptions: list[dict[str, Any]] = []
    for value in gc.get_objects():
        if type(value).__name__ not in class_names or _is_valid(value):
            continue
        descriptions.append({"class": type(value).__name__})
        if len(descriptions) >= limit:
            break
    return descriptions


def _tree_children(top_levels: list[object], cls: type) -> list[object]:
    """Find QObjects owned by top-level test windows, not QApplication."""
    matches: list[object] = []
    for widget in top_levels:
        if not _is_valid(widget):
            continue
        if isinstance(widget, cls):
            matches.append(widget)
        try:
            matches.extend(widget.findChildren(cls))  # type: ignore[attr-defined]
        except RuntimeError:
            continue
    return matches


def drain_deferred_deletes(app, *, cycles: int = 3) -> None:
    """Boundedly deliver only teardown events after owners have been stopped.

    This is test infrastructure, not a substitute for component cleanup.  It
    sends Qt's deferred-delete events and performs a fixed number of ordinary
    event turns so destruction notifications can remove Python-held registry
    entries while the shared QApplication remains alive.
    """
    from PySide6.QtCore import QCoreApplication, QEvent

    for _ in range(cycles):
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()


def settle_pending_widget_updates(app) -> None:
    """Deliver one bounded update turn before fixture teardown starts."""
    from PySide6.QtCore import QCoreApplication, QEvent

    QCoreApplication.sendPostedEvents(None, QEvent.Type.UpdateRequest)
    app.processEvents()


def _global_lifecycle_state(app, *, include_global_wrappers: bool = False) -> dict[str, Any]:
    """Inspect QObject wrappers that can outlive a closed top-level window."""
    from PySide6.QtCore import Qt, QThread, QTimer

    top_level_objects = list(app.topLevelWidgets())
    top_levels = [_object_description(widget) for widget in top_level_objects if _is_valid(widget)]
    popups = []
    for widget in top_level_objects:
        if not _is_valid(widget):
            continue
        try:
            if widget.windowType() == Qt.WindowType.Popup:
                popups.append(_object_description(widget))
        except RuntimeError:
            continue

    if include_global_wrappers:
        main_thread = app.thread()
        qthreads = [
            value
            for value in gc.get_objects()
            if isinstance(value, QThread) and _is_valid(value) and value != main_thread
        ]
        timers = [value for value in gc.get_objects() if isinstance(value, QTimer) and _is_valid(value)]
    else:
        qthreads = _tree_children(top_level_objects, QThread)
        timers = _tree_children(top_level_objects, QTimer)
    running_threads = []
    for thread in qthreads:
        try:
            if thread.isRunning():
                running_threads.append(_object_description(thread))
        except RuntimeError:
            continue
    active_timers = []
    for timer in timers:
        try:
            if timer.isActive():
                active_timers.append(_object_description(timer))
        except RuntimeError:
            continue
    modal = app.activeModalWidget()
    return {
        "top_levels": top_levels,
        "running_qthreads": running_threads,
        "active_timers": active_timers,
        "open_popups": popups,
        "active_modal": _object_description(modal) if modal is not None else None,
    }


def assert_post_test_invariants(app) -> None:
    """Fail a diagnostic run rather than allowing Qt lifetime state to bleed on."""
    if not cleanup_assertions_enabled():
        return
    state = _global_lifecycle_state(app, include_global_wrappers=deep_diagnostics_enabled())
    failures = {key: value for key, value in state.items() if value not in ([], None)}
    if failures:
        raise AssertionError(f"Qt lifecycle cleanup invariant failed: {json.dumps(failures, sort_keys=True)}")


def snapshot(nodeid: str, phase: str) -> None:
    """Append a non-mutating process-state snapshot when diagnostics are enabled."""
    if not diagnostics_enabled():
        return
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        return

    app = QApplication.instance()
    record: dict[str, Any] = {
        "at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "nodeid": nodeid,
        "phase": phase,
        "application": bool(app and _is_valid(app)),
    }
    if app is not None and _is_valid(app):
        record.update(_global_lifecycle_state(app, include_global_wrappers=deep_diagnostics_enabled()))

    if deep_diagnostics_enabled():
        tracked = {
            "QtDataFreshnessPoller",
            "DataSourceRow",
            "MinimalistAtlasWindow",
            "MinimalistSettingsPage",
            "MinimalistLibraryContent",
            "LibraryRecordStateView",
            "PhotoService",
            "PhotoTile",
        }
        live, invalid = _live_python_objects(tracked)
        record["tracked_python_wrappers"] = {
            "live": live,
            "invalid": invalid,
            "invalid_descriptions": _invalid_wrapper_descriptions(tracked),
        }
        try:
            from app.atlas.minimalist.settings_page import MinimalistSettingsPage

            registries = []
            for value in gc.get_objects():
                if not isinstance(value, MinimalistSettingsPage) or not _is_valid(value):
                    continue
                registries.append(len(getattr(value, "source_rows", {})))
            record["dynamic_source_row_registry_counts"] = registries
        except (ImportError, RuntimeError, TypeError):
            record["dynamic_source_row_registry_counts"] = []
    else:
        record["tracked_python_wrappers"] = {"deep_scan": False}
        record["dynamic_source_row_registry_counts"] = []

    trace = Path(os.getenv("EOAT_QT_LIFECYCLE_TRACE", str(Path(os.environ.get("TEMP", ".")) / "eoat-qt-lifecycle.jsonl")))
    trace.parent.mkdir(parents=True, exist_ok=True)
    with trace.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
