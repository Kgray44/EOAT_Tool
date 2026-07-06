from __future__ import annotations

from core.performance import analyze_performance_doctor, log_performance_event, summarize_library_performance


def test_performance_doctor_reports_slowest_operation_cause_and_recommendation(fake_project):
    log_performance_event(fake_project, "startup.load_config", 0.8)
    log_performance_event(fake_project, "workbook.open", 4.2)
    log_performance_event(fake_project, "validation.scan", 2.0)
    log_performance_event(fake_project, "event.dispatch", 0.7)

    summary, warning = analyze_performance_doctor(fake_project)

    assert warning is None
    assert summary.event_count >= 4
    assert summary.slowest_operation == "workbook.open"
    assert summary.slowest_duration_seconds == 4.2
    assert summary.findings
    assert any("Workbook IO" in finding.likely_cause for finding in summary.findings)
    assert all(finding.recommendation for finding in summary.findings)


def test_performance_doctor_covers_report_cache_queue_and_lock(fake_project):
    log_performance_event(fake_project, "report.generation", 1.5)
    log_performance_event(fake_project, "cache.write", 0.8, details={"cache_status": "miss"})
    log_performance_event(fake_project, "background.queue_wait", 0.4)
    log_performance_event(fake_project, "workbook.lock_wait", 0.3)

    summary, _warning = analyze_performance_doctor(fake_project)
    causes = "\n".join(finding.likely_cause for finding in summary.findings)

    assert "Report generation" in causes
    assert "Cache read/write" in causes
    assert "Background queue" in causes
    assert "Workbook lock" in causes


def test_library_performance_summary_reports_targets_and_ui_thread_warnings():
    events = [
        {"operation": "library.open", "duration_seconds": 0.18, "details": {}},
        {"operation": "library.render.visible_cards", "duration_seconds": 0.022, "details": {}},
        {"operation": "library.interaction.search_execute", "duration_seconds": 0.051, "details": {}},
        {"operation": "record.open.eoat", "duration_seconds": 0.041, "details": {}},
        {"operation": "record.relationship_render", "duration_seconds": 0.004, "details": {}},
        {"operation": "record.render.photos_tab_lazy", "duration_seconds": 0.033, "details": {}},
        {"operation": "photo_service.request_thumbnail", "duration_seconds": 0.001, "details": {}},
        {"operation": "photo_service.memory_cache_hit", "duration_seconds": 0.0, "details": {}},
    ]

    summary = summarize_library_performance(events)

    assert summary["status"] == "PASS"
    assert summary["metrics"]["library.open"]["pass"] is True
    assert summary["metrics"]["record.relationship_render"]["max_ms"] == 4.0
    assert summary["thumbnail_cache_hit_rate"] == 1.0
    assert all(count == 0 for count in summary["warnings"].values())


def test_library_performance_summary_fails_on_ui_thread_decode_warning():
    summary = summarize_library_performance(
        [
            {
                "operation": "photo_service.image_decode_worker",
                "duration_seconds": 0.01,
                "details": {"ui_thread_warning": "image_decode_on_ui_thread"},
            }
        ]
    )

    assert summary["status"] == "FAIL"
    assert summary["warnings"]["image_decode_on_ui_thread"] == 1
