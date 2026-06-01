from __future__ import annotations

from openpyxl import load_workbook

from core.fmea_analysis import analyze_fmea, generate_fmea_report
from core.paths import resolve_project_paths


def test_fmea_rpn_and_issue_suggestions(fake_project):
    workbook_path = resolve_project_paths(fake_project).master_workbook
    wb = load_workbook(workbook_path)
    fmea = wb["FMEA Draft"]
    fmea.append(
        [
            "FMEA-1",
            "Plant 4",
            "Press 12",
            "Pick part",
            "Vacuum loss",
            "Part drop",
            "Cup wear",
            "Vacuum sensor",
            "5 - Moderate",
            "4",
            "3",
            "",
            "Inspect cups",
            "",
            "",
            "Open",
            "",
        ]
    )
    issues = wb["Issue Log"]
    issues.append(
        [
            "ISS-1",
            "2026-05-18",
            "Plant 4",
            "Press 13",
            "Engel Viper",
            "Hybrid",
            "Sensor issue",
            "False signal",
            "",
            "",
            "",
            "6",
            "4",
            "4",
            "",
            "",
            "",
            "Open",
            "",
            "",
        ]
    )
    wb.save(workbook_path)
    wb.close()

    summary, error = analyze_fmea(fake_project)
    assert error is None
    assert summary.ranked_rows[0]["RPN"] == 60
    assert summary.suggestions
    assert summary.suggestions[0]["Issue Category"] == "Sensor issue"

    result = generate_fmea_report(fake_project)
    assert result.success is True
    assert result.output_reports
