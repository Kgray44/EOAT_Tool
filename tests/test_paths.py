from __future__ import annotations

from core.paths import resolve_project_paths, validate_looks_like_eoat_project_root
from core.constants import DEFAULT_PROJECT_ROOT


def test_path_resolver_returns_standard_paths(tmp_path):
    paths = resolve_project_paths(tmp_path)

    assert paths.master_workbook.name == "EOAT_Master_Tracker.xlsx"
    assert paths.daily_reports.name == "Daily_Status_Reports"
    assert paths.final_handoff.name == "06_Final_Handoff"
    assert paths.reference_data == tmp_path / "00_Project_Admin" / "reference_data"


def test_project_root_validation_reports_missing_items(tmp_path):
    valid, missing = validate_looks_like_eoat_project_root(tmp_path)

    assert valid is False
    assert any("00_Project_Admin" in item for item in missing)
    assert any("EOAT_Master_Tracker.xlsx" in item for item in missing)


def test_demo_project_loads_without_real_company_data():
    valid, missing = validate_looks_like_eoat_project_root(DEFAULT_PROJECT_ROOT)

    assert valid is True, missing
