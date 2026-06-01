from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from openpyxl import load_workbook

import core.weekly_summary as weekly_summary
from core.logging import log_tool_run
from core.paths import resolve_project_paths
from core.result import ToolResult
from core.weekly_summary import build_weekly_summary_markdown, generate_weekly_summary

REQUIRED_WEEKLY_SECTIONS = [
    "## Executive Summary",
    "## Progress Snapshot",
    "## Task Progress",
    "## Work Completed",
    "## Key Observations",
    "## Issues, Risks, and Data Gaps",
    "## Open Follow-Ups",
    "## Validation Signals",
    "## Reports and Files",
    "## Decisions Needed",
    "## Next Week Plan",
    "## Notes",
]


def _section(markdown: str, heading: str) -> str:
    start = markdown.index(heading)
    level = len(heading) - len(heading.lstrip("#"))
    tail = markdown[start + len(heading) :]
    for match in re.finditer(r"\n(#{1,6}) ", tail):
        if len(match.group(1)) <= level:
            return markdown[start : start + len(heading) + match.start()]
    return markdown[start:]


def _sample_week2_context(project_root: Path) -> dict[str, object]:
    paths = resolve_project_paths(project_root)
    week2_report = paths.daily_reports / "Week2_Day4_Status_2026-05-28.md"
    return {
        "warnings": [],
        "activity": [
            {"tool_name": "Tool", "summary": "", "success": True},
            {
                "tool_name": "Daily Status",
                "summary": "Week2_Day4_Status_2026-05-28: Updated the EOAT master tracker workbook",
                "success": True,
                "files_modified": [str(paths.master_workbook)],
                "files_created": ["Week1_Summary_2026-05-22.md"],
            },
            {
                "tool_name": "Daily Status",
                "summary": "Updated the EOAT master tracker workbook",
                "success": True,
            },
            {
                "tool_name": "Weekly Summary Generator",
                "summary": "Tested weekly report automation",
                "success": True,
            },
        ],
        "open_items_summary": {
            "total_open_items": 576,
            "blocked_items": 0,
            "overdue_followups": 0,
            "missing_evidence_count": 9,
            "data_conflict_count": 1,
            "critical_open_items": 1,
        },
        "open_items": [
            {
                "severity": "Warning",
                "category": "missing_evidence",
                "title": "Missing evidence: Cable Management",
                "status": "Open",
            }
            for _ in range(5)
        ]
        + [
            {
                "severity": "Warning",
                "category": "missing_evidence",
                "title": "Missing evidence: EOAT-Side Pneumatics",
                "status": "Open",
            }
            for _ in range(4)
        ]
        + [
            {
                "severity": "Critical",
                "category": "data_conflict",
                "title": "Workbook row has conflicting audit status",
                "status": "Open",
            }
        ],
        "validation": {"available": False, "summary": "No JSON validation findings were found.", "counts": {}},
        "schedule": {
            "status_counts": {
                "Not started": 0,
                "In progress": 0,
                "Blocked": 0,
                "Complete": 0,
                "Skipped": 0,
            },
            "completed_tasks": [],
            "open_tasks": [],
            "blocked_tasks": [],
        },
        "daily_reports": [str(week2_report)],
        "daily_report_bullets": [
            "Week2_Day4_Status_2026-05-28: Updated the EOAT master tracker workbook",
            "Updated the EOAT master tracker workbook",
            "Tool:",
            "Tested weekly report automation",
        ],
    }


def test_weekly_summary_handles_missing_daily_reports(minimal_fake_project):
    markdown, warnings, metrics = build_weekly_summary_markdown(
        minimal_fake_project,
        week=1,
        generated_at=datetime(2026, 5, 22, 19, 0),
    )

    assert "Week 1 EOAT Project Summary" in markdown
    assert "Use the project schedule as the source of truth" not in markdown
    assert "**Date Range:** Week 1, dates not fully resolved from available source data" in markdown
    assert "## Notes" in markdown
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


def test_weekly_summary_cleans_groups_and_separates_bad_report_signals(monkeypatch, minimal_fake_project):
    paths = resolve_project_paths(minimal_fake_project)
    week2_report = paths.daily_reports / "Week2_Day4_Status_2026-05-28.md"
    week2_report.write_text(
        "\n".join(
            [
                "# Week 2 Day 4",
                "",
                "- Week2_Day4_Status_2026-05-28: Updated the EOAT master tracker workbook",
                "- Updated the EOAT master tracker workbook",
                "- Tool:",
                "- Tested weekly report automation",
            ]
        ),
        encoding="utf-8",
    )
    (paths.daily_reports / "Week1_Day5_Status_2026-05-22.md").write_text("- Older source\n", encoding="utf-8")
    monkeypatch.setattr(
        weekly_summary,
        "_workbook_metrics",
        lambda _root: {
            "EOAT inventory rows": 46,
            "Audited EOATs": 18,
            "audit_completion_percent": 39.1,
            "Engineering issues logged": 0,
            "Interviews logged": 0,
            "Photos indexed": 0,
            "Pilot candidates flagged": 0,
            "Assigned open action items": 0,
        },
    )
    monkeypatch.setattr(
        weekly_summary, "build_weekly_report_context", lambda root, **_kwargs: _sample_week2_context(root)
    )

    markdown, warnings, metrics = build_weekly_summary_markdown(
        minimal_fake_project,
        week=2,
        target_date="2026-05-29",
        generated_at=datetime(2026, 5, 29, 19, 0),
    )

    assert not warnings
    assert metrics["open_followup_groups"] == 3
    assert "Use the project schedule as the source of truth" not in markdown
    assert "**Date Range:** May 28, 2026" in markdown
    assert "Week 2 summary generated from daily reports" not in markdown
    assert "Tool:" not in markdown
    assert "- Updated the EOAT master tracker workbook" in markdown
    assert markdown.count("- Updated the EOAT master tracker workbook") == 1
    assert "Audited EOATs: 18 / 46 (39.1%)" in markdown
    assert "Assigned open action items: 0" in markdown
    assert "Data quality follow-ups: 576 open" in markdown
    assert "Critical data conflicts: 1" in markdown
    assert "Task progress data was not available for this summary." in markdown
    assert "Missing evidence: Cable Management: 5 open entries" in markdown
    assert "Missing evidence: EOAT-Side Pneumatics: 4 open entries" in markdown
    assert "Workbook validation output was not available. Run workbook validation" in markdown
    assert '"findings"' not in markdown
    assert "{" not in markdown

    work_completed = _section(markdown, "## Work Completed")
    key_observations = _section(markdown, "## Key Observations")
    assert "Updated the EOAT master tracker workbook" not in key_observations
    assert work_completed != key_observations

    created_this_week = _section(markdown, "### Created This Week")
    assert "Week1" not in created_this_week
    assert "Week2_Day4_Status_2026-05-28.md" in _section(markdown, "### Source Reports Referenced")
    for heading in REQUIRED_WEEKLY_SECTIONS:
        assert heading in markdown
