from __future__ import annotations

from core.dashboard_cache import (
    cached_snapshot,
    cached_snapshot_status,
    dashboard_cache_path,
    load_dashboard_cache,
    save_dashboard_cache,
    source_metadata,
    stale_reasons,
)


def test_dashboard_cache_round_trip(fake_project):
    snapshot = {"cards": {"EOAT Documentation Rows": "2"}, "recommendations": ["Keep going"], "activity_text": "ok"}

    path = save_dashboard_cache(fake_project, snapshot)
    payload, warning = load_dashboard_cache(fake_project)
    loaded, stale, cached_warning = cached_snapshot(fake_project)

    assert path == dashboard_cache_path(fake_project)
    assert warning is None
    assert payload is not None
    assert loaded == snapshot
    assert stale is False
    assert cached_warning is None


def test_dashboard_cache_marks_source_changes_stale(fake_project):
    save_dashboard_cache(fake_project, {"cards": {}, "recommendations": [], "activity_text": ""})

    activity_log = fake_project / "00_Project_Admin" / "Activity_Logs" / "activity_log.jsonl"
    activity_log.write_text('{"tool_name":"test"}\n', encoding="utf-8")
    _snapshot, stale, warning = cached_snapshot(fake_project)
    payload, _warning = load_dashboard_cache(fake_project)
    reasons = stale_reasons(fake_project, payload)

    assert warning is None
    assert stale is True
    assert any("activity_log.jsonl" in reason for reason in reasons)


def test_dashboard_cache_bad_json_recovers_gracefully(fake_project):
    path = dashboard_cache_path(fake_project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not-json", encoding="utf-8")

    snapshot, stale, warning = cached_snapshot(fake_project)

    assert snapshot is None
    assert stale is True
    assert "Could not load dashboard cache" in warning


def test_dashboard_cache_source_metadata_tracks_phase6_sources(fake_project):
    paths = fake_project / "00_Project_Admin"
    (paths / "logs").mkdir(parents=True, exist_ok=True)
    (paths / "logs" / "scheduled_tools.log").write_text("{}\n", encoding="utf-8")
    (fake_project / "project_data").mkdir(exist_ok=True)
    (fake_project / "project_data" / "annotations.sqlite").write_text("", encoding="utf-8")
    robot_info = fake_project / "01_EOAT_Audit" / "EOAT_Audit_Database" / "Robot_Info.xlsx"
    robot_info.write_text("placeholder", encoding="utf-8")
    validation = paths / "Validation_Reports" / "Foundation_Validation_2026-05-27_1200.json"
    validation.parent.mkdir(parents=True, exist_ok=True)
    validation.write_text("{}", encoding="utf-8")
    doc_gap = fake_project / "03_Standards" / "Documentation_Gap_Reports" / "Documentation_Gap_Report_2026-05-27.md"
    doc_gap.parent.mkdir(parents=True, exist_ok=True)
    doc_gap.write_text("# gaps\n", encoding="utf-8")
    exports = fake_project / "06_Final_Handoff" / "Annotation_Exports"
    exports.mkdir(parents=True, exist_ok=True)
    (exports / "open_items_report_2026-05-27.md").write_text("# open\n", encoding="utf-8")

    metadata = source_metadata(fake_project)
    sources = {source["key"]: source for source in metadata["sources"]}

    for key in [
        "master_tracker_workbook",
        "activity_log",
        "scheduled_report_log",
        "daily_report_folder",
        "weekly_report_folder",
        "task_schedule_files",
        "annotation_database",
        "robot_info_workbook",
        "validation_findings_json",
        "photo_index_files",
        "documentation_gap_outputs",
        "open_items_outputs",
    ]:
        assert key in sources
    assert sources["scheduled_report_log"]["exists"] is True
    assert sources["validation_findings_json"]["file_count"] == 1
    assert sources["documentation_gap_outputs"]["file_count"] == 1
    assert sources["open_items_outputs"]["file_count"] == 1


def test_cached_snapshot_status_explains_staleness(fake_project):
    save_dashboard_cache(
        fake_project, {"cards": {"Dashboard Cache": "Updated"}, "recommendations": [], "activity_text": "ok"}
    )
    activity_log = fake_project / "00_Project_Admin" / "Activity_Logs" / "activity_log.jsonl"
    activity_log.write_text('{"tool_name":"test"}\n', encoding="utf-8")

    status = cached_snapshot_status(fake_project)

    assert status.cache_hit is True
    assert status.stale is True
    assert "Dashboard cache stale because" in status.stale_explanation
