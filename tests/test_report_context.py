from __future__ import annotations

from datetime import date

from core.logging import log_tool_run
from core.report_context import build_daily_report_context, build_weekly_report_context, daily_summary_cli_items
from core.result import ToolResult


def test_daily_report_context_uses_activity_log(fake_project):
    result = ToolResult.ok(
        "audit_save",
        "Audit Save",
        "Audit saved for scheduled-report context.",
        files_created=["00_Project_Admin/Daily_Status_Reports/example.md"],
    )
    assert log_tool_run(result, fake_project) is None

    context = build_daily_report_context(fake_project, target_date=date(2026, 5, 20), week=1, day=3)
    cli_items = daily_summary_cli_items(context)

    assert any("Audit saved for scheduled-report context" in line for line in context["activity_lines"])
    assert any("Audit saved for scheduled-report context" in line for line in cli_items["completed"])


def test_weekly_report_context_collects_daily_reports_and_open_item_shape(fake_project):
    context = build_weekly_report_context(fake_project, week=1, target_date=date(2026, 5, 22))

    assert context["week"] == 1
    assert isinstance(context["daily_reports"], list)
    assert "open_items_summary" in context
    assert "validation" in context
