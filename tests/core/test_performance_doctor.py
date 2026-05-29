from __future__ import annotations

from core.performance import analyze_performance_doctor, log_performance_event


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
