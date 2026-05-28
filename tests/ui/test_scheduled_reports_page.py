from __future__ import annotations

import pytest

from app.pages.scheduled_reports import ScheduledReportsPage
from core.paths import resolve_project_paths
from core.result import ToolResult
from tests.ui.helpers import find_button, table_text


pytestmark = pytest.mark.usability


def test_scheduled_reports_page_shows_preview_actions_and_preflight(qapp, fake_config, fake_project, monkeypatch):
    paths = resolve_project_paths(fake_project)

    def fake_status(_project_root):
        return {
            "daily": {
                "schedule": "Monday-Thursday at 7:00 PM",
                "task": {"installed": False},
                "last_status": "Skipped",
                "last_report": "",
                "missed_dates": ["2026-05-19"],
                "next_expected_run": "2026-05-20T19:00:00-04:00",
            },
            "weekly": {
                "schedule": "Friday at 7:00 PM",
                "task": {"installed": True, "state": "Ready"},
                "last_status": "Success",
                "last_report": "",
                "missed_dates": [],
                "next_expected_run": "2026-05-22T19:00:00-04:00",
            },
            "scheduled_log": str(paths.logs / "scheduled_tools.log"),
            "paths": {
                "daily_reports": str(paths.daily_reports),
                "weekly_reports": str(paths.weekly_reports),
                "logs": str(paths.logs),
            },
        }

    def fake_preflight(_project_root):
        return ToolResult.ok(
            "scheduled_report_preflight",
            "Scheduled Report Preflight",
            "Preflight ok.",
            structured_data={"checks": [{"name": "PowerShell executable", "status": "PASS", "message": "found", "details": ""}]},
        )

    monkeypatch.setattr("app.pages.scheduled_reports.get_scheduled_report_status", fake_status)
    monkeypatch.setattr("app.pages.scheduled_reports.run_scheduler_preflight", fake_preflight)

    page = ScheduledReportsPage(fake_config)
    page.show()

    assert page.cards["Daily Task Installed"].value_label.text() == "No"
    assert page.cards["Weekly Task Installed"].value_label.text() == "Yes (Ready)"
    assert find_button(page, "Run Daily Dry Run")
    assert find_button(page, "Generate Weekly Now")
    assert "daily_summary" in table_text(page.preview_table)
    assert "PowerShell executable" in table_text(page.preflight_table)
