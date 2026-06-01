from __future__ import annotations

from openpyxl import load_workbook

from core.audit.history import append_audit_history
from core.logging import log_tool_run
from core.paths import resolve_project_paths
from core.result import ToolResult
from core.timeline import build_timeline, timeline_event_counts
from core.workbook_schema import get_expected_headers


def test_timeline_tracks_audit_field_robot_and_manual_override_events(fake_project):
    append_audit_history(
        fake_project,
        "AUD-TL-001",
        "updated",
        {"Robot Type": "Old", "Manual Completion Override": "No"},
        {"Robot Type": "New", "Manual Completion Override": "Yes"},
    )

    events = build_timeline(fake_project)
    event_types = {event.event_type for event in events}

    assert "audit_updated" in event_types
    assert "field_changed" in event_types
    assert "robot_info_updated" in event_types
    assert "manual_override_applied" in event_types


def test_timeline_tracks_reports_pm_and_photo_evidence(fake_project):
    log_tool_run(
        ToolResult.ok(
            "pm_checklist_generator",
            "PM Checklist",
            "Generated PM checklist.",
            files_created=[
                str(fake_project / "03_Standards" / "PM_Checklist_Draft" / "Generated_Checklists" / "PM.md")
            ],
        ),
        fake_project,
    )
    log_tool_run(
        ToolResult.ok(
            "kpi_dashboard_report",
            "KPI Report",
            "Generated report.",
            files_created=[str(fake_project / "02_KPI_Data" / "Dashboard_Exports" / "KPI.md")],
        ),
        fake_project,
    )
    workbook = load_workbook(resolve_project_paths(fake_project).master_workbook)
    ws = workbook["Photo Index"]
    headers = get_expected_headers("Photo Index")
    row = {header: "" for header in headers}
    row.update(
        {
            "Photo ID": "PHOTO-1",
            "Photo Filename": "eoat.jpg",
            "Related Audit ID": "AUD-TL-002",
            "Press/Machine #": "Press 12",
            "Date Taken": "2026-05-18",
        }
    )
    ws.append([row.get(header, "") for header in headers])
    workbook.save(resolve_project_paths(fake_project).master_workbook)
    workbook.close()

    counts = timeline_event_counts(fake_project)

    assert counts["pm_checklist_generated"] >= 1
    assert counts["report_generated"] >= 1
    assert counts["photo_evidence_added"] >= 1
