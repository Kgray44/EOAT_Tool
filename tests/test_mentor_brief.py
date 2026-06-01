from __future__ import annotations

from openpyxl import load_workbook

from core.mentor_brief import build_mentor_brief_markdown, generate_mentor_brief
from core.paths import resolve_project_paths


def test_mentor_brief_handles_missing_logs(fake_project):
    markdown, warnings, metrics = build_mentor_brief_markdown(fake_project, days=7)

    assert "Mentor Check-In Brief" in markdown
    assert metrics["activity_entries"] == 0
    assert warnings == []


def test_mentor_brief_summarizes_blockers_and_questions(fake_project):
    paths = resolve_project_paths(fake_project)
    wb = load_workbook(paths.master_workbook)
    ws = wb["Action Items"]
    ws.append(["ACT-1", "2026-05-18", "Find BOM", "Press 12", "KG", "High", "", "Blocked", "", "Need source"])
    issue = wb["Issue Log"]
    issue.append(
        [
            "ISS-1",
            "2026-05-18",
            "Plant 4",
            "Press 12",
            "Wittmann R9",
            "Vacuum",
            "Vacuum loss",
            "Drops parts",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "Open",
            "",
            "",
        ]
    )
    wb.save(paths.master_workbook)
    wb.close()

    result = generate_mentor_brief(fake_project, days=7)

    assert result.success is True
    assert result.metrics["blocked_actions"] == 1
    assert result.metrics["open_issues"] == 1
    assert result.output_reports
