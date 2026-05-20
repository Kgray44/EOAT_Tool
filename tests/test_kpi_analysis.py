from __future__ import annotations

from openpyxl import load_workbook

from core.kpi_analysis import analyze_kpis, generate_kpi_dashboard_report
from core.paths import resolve_project_paths


def test_kpi_analysis_empty_baseline(fake_project):
    summary, error = analyze_kpis(fake_project)
    assert error is None
    assert summary.metrics["kpi_rows"] == 0
    assert summary.metrics["total_downtime_minutes"] == 0


def test_kpi_analysis_totals(fake_project):
    workbook_path = resolve_project_paths(fake_project).master_workbook
    wb = load_workbook(workbook_path)
    ws = wb["KPI Baseline"]
    ws.append(["KPI-1", "2026-05-18", "Plant 4", "Press 12", "", "Family", "Vacuum", 30, "Yes", 3, 2, 12, "Drop", 15.5, 2, "", "Manual", ""])
    wb.save(workbook_path)
    wb.close()

    summary, error = analyze_kpis(fake_project)
    assert error is None
    assert summary.metrics["total_downtime_minutes"] == 30
    assert summary.metrics["part_drops"] == 3
    assert summary.scrap_reasons["Drop"] == 1

    result = generate_kpi_dashboard_report(fake_project)
    assert result.success is True
    assert result.output_reports

