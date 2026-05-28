from __future__ import annotations

from openpyxl import load_workbook

from core.audit_constants import ENTRY_TYPE_COMPATIBLE, ENTRY_TYPE_FIELD, SOURCE_AUDIT_ID_FIELD
from core.paths import resolve_project_paths
from core.press_view import build_press_view_groups, export_press_summary
from core.workbook_schema import get_expected_headers


def _append_inventory_row(workbook_path, values):
    workbook = load_workbook(workbook_path)
    try:
        ws = workbook["EOAT Inventory"]
        headers = get_expected_headers("EOAT Inventory")
        ws.append([values.get(header, "") for header in headers])
        workbook.save(workbook_path)
    finally:
        workbook.close()


def test_press_view_groups_physical_and_compatible_entries(usability_fake_project):
    paths = resolve_project_paths(usability_fake_project)
    _append_inventory_row(
        paths.master_workbook,
        {
            "Audit ID": "AUD-COMPAT-101",
            "Audit Date": "2026-05-19",
            "Press/Machine #": "Press 101",
            "Tool #": "TOOL-A",
            "EOAT Type": "Vacuum",
            "Status": "Compatible",
            ENTRY_TYPE_FIELD: ENTRY_TYPE_COMPATIBLE,
            SOURCE_AUDIT_ID_FIELD: "AUD-20260518-001",
        },
    )

    groups = build_press_view_groups(usability_fake_project)
    group = next(item for item in groups if item.machine == "101")

    assert len(group.physical_audits) == 1
    assert len(group.compatible_entries) == 1
    assert group.photo_count == 1
    assert group.pilot_candidacy == "Yes"
    assert group.average_compliance_score >= 0
    assert isinstance(group.worst_compliance_category, str)


def test_press_view_export_is_no_overwrite_project_output(usability_fake_project):
    result = export_press_summary(usability_fake_project, "101")

    assert result.success is True
    assert result.output_reports
    assert "Press_101_Summary" in result.output_reports[0]
