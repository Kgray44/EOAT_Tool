from __future__ import annotations

from openpyxl import Workbook

from core.audit_by_press import AUDIT_BY_PRESS_SHEET
from core.constants import EXPECTED_NUMBERED_FOLDERS
from core.validation import validate_project_foundation
from core.paths import resolve_project_paths
from core.workbook_schema import get_expected_headers, get_expected_sheets


def test_validate_project_foundation_on_temp_project(tmp_path):
    for folder in EXPECTED_NUMBERED_FOLDERS:
        (tmp_path / folder).mkdir(parents=True)
    (tmp_path / "00_Project_Admin" / "Daily_Status_Reports").mkdir()
    (tmp_path / "00_Project_Admin" / "Weekly_Status_Reports").mkdir()
    (tmp_path / "00_Project_Admin" / "Activity_Logs").mkdir()
    (tmp_path / "README.md").write_text("Project", encoding="utf-8")
    (tmp_path / "00_Project_Admin" / "project_schedule_week1.json").write_text('{"week": 1, "days": {}}', encoding="utf-8")
    (tmp_path / "00_Project_Admin" / "task_progress_week1.json").write_text('{"tasks": []}', encoding="utf-8")
    workbook_dir = tmp_path / "01_EOAT_Audit" / "EOAT_Audit_Database"
    workbook_dir.mkdir(parents=True)

    workbook = Workbook()
    default = workbook.active
    workbook.remove(default)
    for sheet_name in get_expected_sheets():
        sheet = workbook.create_sheet(sheet_name)
        sheet.append(get_expected_headers(sheet_name))
    workbook.save(workbook_dir / "EOAT_Master_Tracker.xlsx")

    result = validate_project_foundation(tmp_path)

    assert result.success is True
    assert not result.errors
    assert result.metrics["missing_key_inventory_header_count"] == 0
    assert any("Audit by Press view missing or stale" in warning for warning in result.warnings)


def test_validate_project_foundation_missing_project(tmp_path):
    result = validate_project_foundation(tmp_path / "missing")

    assert result.success is False
    assert result.errors


def _append_inventory_row(workbook_path, values):
    from openpyxl import load_workbook

    workbook = load_workbook(workbook_path)
    ws = workbook["EOAT Inventory"]
    headers = [cell.value for cell in ws[1]]
    ws.append([values.get(header, "") for header in headers])
    workbook.save(workbook_path)
    workbook.close()


def test_workbook_health_flags_missing_major_inventory_header(fake_project):
    workbook_path = resolve_project_paths(fake_project).master_workbook
    workbook = Workbook()
    workbook.remove(workbook.active)
    for sheet_name in get_expected_sheets():
        sheet = workbook.create_sheet(sheet_name)
        headers = [header for header in get_expected_headers(sheet_name) if header != "Tool #"]
        sheet.append(headers)
    workbook.save(workbook_path)
    workbook.close()

    result = validate_project_foundation(fake_project)

    assert result.success is False
    assert any("Missing major EOAT Inventory header: Tool #" in error for error in result.errors)


def test_workbook_health_flags_na_in_major_columns(fake_project):
    workbook_path = resolve_project_paths(fake_project).master_workbook
    _append_inventory_row(
        workbook_path,
        {
            "Audit ID": "AUD-NA-MAJOR",
            "Audit Date": "2026-05-18",
            "Auditor": "KG",
            "Plant/Area": "Plant 4",
            "Press/Machine #": "N/A",
            "Tool #": "N/A",
            "Robot Type": "Wittmann R9",
            "EOAT Type": "Vacuum",
            "Connection Type": "N/A",
            "Cleanroom/Non-Cleanroom": "Whiteroom",
            "Status": "In Progress",
            "Priority": "Medium",
            "Known Issues": "N/A",
        },
    )

    result = validate_project_foundation(fake_project)

    assert result.metrics["major_na_cell_count"] >= 4
    assert any("major EOAT Inventory cell(s) contain N/A" in warning for warning in result.warnings)


def test_workbook_health_allows_na_for_non_applicable_tooling_fields(fake_project):
    workbook_path = resolve_project_paths(fake_project).master_workbook
    headers = get_expected_headers("EOAT Inventory")
    values = {header: "N/A" for header in headers}
    values.update(
        {
            "Audit ID": "AUD-NONAPPLICABLE-NA",
            "Audit Date": "2026-05-18",
            "Auditor": "KG",
            "Plant/Area": "Plant 4",
            "Press/Machine #": "Press 12",
            "Tool #": "DEMO-PN-1200",
            "Robot Type": "Wittmann R9",
            "EOAT Type": "Mechanical / Gripper",
            "Connection Type": "ATI",
            "Cleanroom/Non-Cleanroom": "Whiteroom",
            "Status": "In Progress",
            "Priority": "Medium",
            "Known Issues": "No issues observed.",
            "Part Family": "Housing",
            "Tubing Condition": "OK",
            "Cable Management Condition": "OK",
            "Photos Taken?": "No",
            "Cup Type/Material": "N/A",
            "Cup Diameter/Size": "N/A",
            "Gripper Model": "Zimmer GPP",
            "Gripper Size": "25 mm",
        }
    )
    _append_inventory_row(workbook_path, values)

    result = validate_project_foundation(fake_project)

    assert result.metrics["major_na_cell_count"] == 0
    assert not any("Cup Diameter/Size" in warning for warning in result.warnings)
    assert not any("Cup Type/Material" in warning for warning in result.warnings)


def test_workbook_health_summarizes_blank_saved_cells_without_per_cell_noise(fake_project):
    workbook_path = resolve_project_paths(fake_project).master_workbook
    _append_inventory_row(
        workbook_path,
        {
            "Audit ID": "AUD-BLANK-DETAILS",
            "Audit Date": "2026-05-18",
            "Auditor": "KG",
            "Plant/Area": "Plant 4",
            "Press/Machine #": "Press 12",
            "Tool #": "DEMO-PN-1200",
            "Robot Type": "Wittmann R9",
            "EOAT Type": "Vacuum",
            "Connection Type": "ATI",
            "Cleanroom/Non-Cleanroom": "Whiteroom",
            "Status": "In Progress",
            "Priority": "Medium",
            "Known Issues": "No issue observed.",
        },
    )

    result = validate_project_foundation(fake_project)
    blank_warnings = [warning for warning in result.warnings if "saved EOAT Inventory cell(s) are blank" in warning]

    assert result.metrics["blank_saved_audit_cell_count"] > 0
    assert len(blank_warnings) == 1


def test_workbook_health_treats_audit_by_press_as_regenerable_warning(fake_project):
    workbook_path = resolve_project_paths(fake_project).master_workbook
    workbook = Workbook()
    workbook.remove(workbook.active)
    for sheet_name in get_expected_sheets():
        sheet = workbook.create_sheet(sheet_name)
        sheet.append(get_expected_headers(sheet_name))
    assert AUDIT_BY_PRESS_SHEET not in workbook.sheetnames
    workbook.save(workbook_path)
    workbook.close()

    result = validate_project_foundation(fake_project)

    assert result.success is True
    assert not any(AUDIT_BY_PRESS_SHEET in error for error in result.errors)
    assert any("Audit by Press view missing or stale; refresh generated view." == warning for warning in result.warnings)

