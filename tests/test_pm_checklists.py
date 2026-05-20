from __future__ import annotations

from openpyxl import load_workbook

from core.paths import resolve_project_paths
from core.pm_checklists import build_pm_checklist_markdown, generate_pm_checklists


def test_generate_generic_vacuum_mechanical_hybrid_checklists(fake_project):
    result = generate_pm_checklists(fake_project, generic=True)

    assert result.success is True
    assert len([path for path in result.output_reports if path.endswith(".md")]) == 3


def test_pm_checklist_type_specific_content():
    vacuum, _ = build_pm_checklist_markdown(None, "Vacuum")
    mechanical, _ = build_pm_checklist_markdown(None, "Mechanical Gripper")
    hybrid, _ = build_pm_checklist_markdown(None, "Hybrid")

    assert "vacuum cups" in vacuum.lower()
    assert "gripper fingers" in mechanical.lower()
    assert "coordination between vacuum and mechanical" in hybrid.lower()


def test_generate_eoat_specific_checklist_and_missing_data_warning(fake_project):
    workbook_path = resolve_project_paths(fake_project).master_workbook
    wb = load_workbook(workbook_path)
    ws = wb["EOAT Inventory"]
    ws.append(["AUD-1", "2026-05-18", "KG", "Plant 4", "Press 12", "Wittmann R9", "", "", "", "", "", "Vacuum"])
    wb.save(workbook_path)
    wb.close()

    result = generate_pm_checklists(fake_project, press="Press 12")

    assert result.success is True
    assert result.output_reports
    assert result.warnings
    assert "Press_12" in result.output_reports[0]
