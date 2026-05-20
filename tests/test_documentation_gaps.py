from __future__ import annotations

from openpyxl import load_workbook

from core.documentation_gaps import generate_documentation_gap_report, scan_documentation_gaps
from core.paths import resolve_project_paths


def test_documentation_gap_scanner_detects_missing_fields(fake_project):
    workbook_path = resolve_project_paths(fake_project).master_workbook
    wb = load_workbook(workbook_path)
    ws = wb["EOAT Inventory"]
    ws.append(["AUD-1", "2026-05-18", "KG", "Plant 4", "Press 12", "Wittmann R9"])
    wb.save(workbook_path)
    wb.close()

    summary, error = scan_documentation_gaps(fake_project)
    assert error is None
    assert summary.metrics["eoats_scanned"] == 1
    assert summary.metrics["critical_gaps"] > 0
    assert "EOAT Type" in summary.missing_field_counts

    result = generate_documentation_gap_report(fake_project)
    assert result.success is True
    assert len(result.output_reports) == 2

