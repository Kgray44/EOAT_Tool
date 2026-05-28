from __future__ import annotations

import json

from core.performance import (
    log_performance,
    log_performance_event,
    performance_jsonl_path,
    read_recent_performance_events,
    summarize_performance,
)


def test_structured_performance_log_writes_valid_jsonl(fake_project):
    warning = log_performance_event(
        fake_project,
        "dashboard.quick_refresh",
        0.1234,
        success=True,
        source="home",
        page_tool="home",
        details={"cache_status": "hit"},
        warning_count=1,
    )

    assert warning is None
    path = performance_jsonl_path(fake_project)
    payload = json.loads(path.read_text(encoding="utf-8").splitlines()[-1])
    assert payload["operation"] == "dashboard.quick_refresh"
    assert payload["duration_seconds"] == 0.1234
    assert payload["success"] is True
    assert payload["source"] == "home"
    assert payload["page_tool"] == "home"
    assert payload["details"]["cache_status"] == "hit"
    assert payload["warning_count"] == 1


def test_log_performance_keeps_text_log_and_adds_jsonl(fake_project):
    warning = log_performance(fake_project, "app_start.shell_visible", 1.5, source="app_start", page_tool="main")

    assert warning is None
    text_log = fake_project / "00_Project_Admin" / "logs" / "performance.log"
    assert "app_start.shell_visible" in text_log.read_text(encoding="utf-8")
    events, read_warning = read_recent_performance_events(fake_project)
    assert read_warning is None
    assert events[0]["operation"] == "app_start.shell_visible"


def test_performance_summary_identifies_slowest_and_cache_counts(fake_project):
    log_performance_event(fake_project, "dashboard.quick_refresh", 0.1, details={"cache_status": "hit"})
    log_performance_event(fake_project, "dashboard.quick_refresh", 0.2, details={"cache_status": "stale"})
    log_performance_event(fake_project, "dashboard.deep_refresh", 3.5, details={"cache_updated": True})
    log_performance_event(fake_project, "task.validation", 2.0, warning_count=2, error_count=1)

    events, warning = read_recent_performance_events(fake_project)
    summary = summarize_performance(events)

    assert warning is None
    assert summary["slowest_operations"][0]["operation"] == "dashboard.deep_refresh"
    assert summary["cache"]["hit"] == 1
    assert summary["cache"]["stale"] == 1
    assert summary["warning_count"] == 2
    assert summary["error_count"] == 1
