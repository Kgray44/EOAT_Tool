from __future__ import annotations

from openpyxl import load_workbook

from core.deliverable_check import check_deliverables, run_final_deliverable_check
from core.paths import resolve_project_paths


def test_deliverable_check_detects_missing_and_partial(fake_project):
    statuses, warnings = check_deliverables(fake_project)
    by_name = {item.name: item for item in statuses}

    assert warnings == []
    assert by_name["EOAT inventory database"].status == "Partial"
    assert by_name["EOAT standard design guideline"].status == "Missing"
    assert by_name["Handoff package"].status == "Missing"


def test_deliverable_check_detects_found_deliverables(fake_project):
    paths = resolve_project_paths(fake_project)
    wb = load_workbook(paths.master_workbook)
    ws = wb["EOAT Inventory"]
    ws.append(["AUD-1", "2026-05-18", "KG", "Plant 4", "Press 12", "Wittmann R9", "", "", "", "", "", "Vacuum"])
    wb.save(paths.master_workbook)
    wb.close()
    paths.pm_generated_checklists.mkdir(parents=True, exist_ok=True)
    (paths.pm_generated_checklists / "PM_Checklist_Test.md").write_text("# PM", encoding="utf-8")

    statuses, _warnings = check_deliverables(fake_project)
    by_name = {item.name: item for item in statuses}

    assert by_name["EOAT inventory database"].status == "Found"
    assert by_name["PM checklist"].status == "Found"

    result = run_final_deliverable_check(fake_project)
    assert result.success is True
    assert result.output_reports
