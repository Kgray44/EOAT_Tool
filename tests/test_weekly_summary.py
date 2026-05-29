from __future__ import annotations

import json

from openpyxl import load_workbook

from core.logging import log_tool_run
from core.paths import resolve_project_paths
from core.result import ToolResult
from core.weekly_summary import build_weekly_summary_markdown, generate_weekly_summary


def test_weekly_summary_handles_missing_daily_reports(fake_project):
    markdown, warnings, metrics = build_weekly_summary_markdown(fake_project, week=1)

    assert "Week 1 EOAT Project Summary" in markdown
    assert "## Weekly Engineering Brief" in markdown
    assert "Estimated or subjective values must remain labeled" in markdown
    assert warnings
    assert metrics["daily_reports_found"] == 0


def test_weekly_summary_combines_reports_activity_and_metrics(fake_project):
    paths = resolve_project_paths(fake_project)
    (paths.daily_reports / "Week1_Day1_Status_2026-05-18.md").write_text("- Completed audit setup\n", encoding="utf-8")
    (fake_project / "00_Project_Admin" / "task_progress_week1.json").write_text(
        json.dumps({"tasks": [{"id": "T1", "day": "1", "task": "Audit Press 12", "status": "Complete"}]}),
        encoding="utf-8",
    )
    wb = load_workbook(paths.master_workbook)
    ws = wb["EOAT Inventory"]
    ws.append(["AUD-1", "2026-05-18", "KG", "Plant 4", "Press 12", "Wittmann R9", "", "", "", "", "", "Vacuum"])
    wb.save(paths.master_workbook)
    wb.close()
    log_tool_run(ToolResult.ok("test", "Test Tool", "Did work"), fake_project)

    result = generate_weekly_summary(fake_project, week=1, notes="Manual note")

    assert result.success is True
    assert result.output_reports
    text = result.output_reports[0]
    assert text.endswith(".md")
    assert result.metrics["daily_reports_found"] == 1
    assert result.metrics["EOAT inventory rows"] == 1
