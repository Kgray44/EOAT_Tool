from __future__ import annotations

from openpyxl import load_workbook

from core.paths import resolve_project_paths
from core.pilot_scoring import generate_pilot_ranking_report, rank_pilot_candidates


def test_pilot_scoring_suggests_from_inventory_flags(fake_project):
    workbook_path = resolve_project_paths(fake_project).master_workbook
    wb = load_workbook(workbook_path)
    inv = wb["EOAT Inventory"]
    inv_headers = [cell.value for cell in inv[1]]
    inventory_row = {header: "" for header in inv_headers}
    inventory_row.update(
        {
            "Audit ID": "AUD-1",
            "Audit Date": "2026-05-18",
            "Auditor": "KG",
            "Plant/Area": "Plant 4",
            "Press/Machine #": "Press 12",
            "Robot Type": "Wittmann R9",
            "EOAT Type": "Vacuum",
            "Known Issues": "Drops parts",
            "Scrap/Quality Concern?": "Yes",
            "Status": "Candidate for pilot",
            "Priority": "High",
            "Pilot Candidate?": "Yes",
        }
    )
    inv.append([inventory_row.get(header, "") for header in inv_headers])
    issues = wb["Issue Log"]
    issues.append(["ISS-1", "2026-05-18", "Plant 4", "Press 12", "Wittmann R9", "Vacuum", "Part drop", "", "", "", "", "8", "5", "4", "", "", "", "Open", "", ""])
    kpi = wb["KPI Baseline"]
    kpi.append(["KPI-1", "2026-05-18", "Plant 4", "Press 12", "", "", "Vacuum", 30, "Yes", 4, 1, 20, "Drop", 12.5, 2, "", "Manual", ""])
    wb.save(workbook_path)
    wb.close()

    summary, error = rank_pilot_candidates(fake_project)
    assert error is None
    assert summary.metrics["candidates_evaluated"] == 1
    assert summary.ranked_candidates[0]["Total Score"] > 0
    assert summary.ranked_candidates[0]["Confidence"] in {"High", "Medium"}

    result = generate_pilot_ranking_report(fake_project)
    assert result.success is True


def test_pilot_scoring_empty_candidates(fake_project):
    summary, error = rank_pilot_candidates(fake_project)
    assert error is None
    assert summary.metrics["candidates_evaluated"] == 0
