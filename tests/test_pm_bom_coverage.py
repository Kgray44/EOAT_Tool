from __future__ import annotations

from core.pm_bom_coverage import (
    build_pm_bom_coverage,
    is_bom_available,
    is_gripper_preset_known_for_row,
    is_spare_parts_info_missing,
    standard_parts_opportunities,
)


def test_pm_bom_coverage_hooks_flag_missing_docs_and_known_gripper(fake_project):
    row = {
        "Audit ID": "AUD-PMBOM-001",
        "Press/Machine #": "Press 12",
        "EOAT Type": "Mechanical / Gripper",
        "Status": "Complete",
        "Gripper Model": "Large Double Gripper",
        "Spare Parts Identified?": "No",
        "Drawing/CAD Available?": "No",
        "BOM Available?": "No",
        "Process Binder Complete?": "No",
    }

    coverage = build_pm_bom_coverage(fake_project, row)

    assert is_spare_parts_info_missing(row) is True
    assert is_bom_available(row) is False
    assert is_gripper_preset_known_for_row(row, fake_project) is True
    assert coverage.gripper_preset_known is True
    assert coverage.documentation_photo_evidence_missing is True
    assert "BOM Available?" in coverage.missing_documentation_fields
    assert any("gripper preset" in item.casefold() for item in standard_parts_opportunities(row, fake_project))
