from __future__ import annotations

from openpyxl import load_workbook

from core.issue_analysis import analyze_issues, generate_issue_analysis_report
from core.paths import resolve_project_paths


def test_issue_analysis_empty_issue_log(fake_project):
    summary, error = analyze_issues(fake_project)

    assert error is None
    assert summary.metrics["issues_logged"] == 0
    assert summary.suggested_fmea == []


def test_issue_analysis_counts_and_suggestions(fake_project):
    workbook_path = resolve_project_paths(fake_project).master_workbook
    wb = load_workbook(workbook_path)
    ws = wb["Issue Log"]
    ws.append([
        "ISS-1",
        "2026-05-18",
        "Plant 4",
        "Press 12",
        "Wittmann R9",
        "Vacuum",
        "Vacuum loss",
        "Part dropped",
        "Cup wear",
        "Operator note",
        "Downtime",
        "8 - High",
        "",
        "5",
        "",
        "Replace cups",
        "",
        "Open",
        "",
        "",
    ])
    wb.save(workbook_path)
    wb.close()

    summary, error = analyze_issues(fake_project)
    assert error is None
    assert summary.category_counts["Vacuum loss"] == 1
    assert summary.press_counts["Press 12"] == 1
    assert summary.metrics["missing_risk_count"] == 1
    assert summary.suggested_fmea[0]["Issue Category"] == "Vacuum loss"

    result = generate_issue_analysis_report(fake_project)
    assert result.success is True
    assert result.output_reports

