from __future__ import annotations

import json

import pytest
from openpyxl import load_workbook
from PySide6.QtWidgets import QComboBox, QTextEdit

from app.pages.audit import AuditPage
from core.audit_entries import save_audit_entry
from core.workbook_io import row_dicts, workbook_sheet_names
from tests.fixtures.reference_workbooks import create_press_reference_workbooks
from tests.ui.helpers import click_button, wait_for_background_tasks, wait_until


pytestmark = pytest.mark.usability


def _set_field(page: AuditPage, field: str, value: str) -> None:
    widget = page.audit_fields[field]
    if isinstance(widget, QComboBox):
        if widget.findText(value) >= 0:
            widget.setCurrentText(value)
        else:
            widget.setEditText(value)
    elif isinstance(widget, QTextEdit):
        widget.setPlainText(value)
    else:
        widget.setText(value)


def _seed_audit(project_root, audit_id: str, **overrides):
    entry = {
        "Audit ID": audit_id,
        "Audit Date": "2026-05-18",
        "Auditor": "Original Auditor",
        "Plant/Area": "Plant 4",
        "Press/Machine #": "Press 12",
        "Tool #": "DEMO-PN-1200",
        "Robot Type": "Wittmann R9",
        "Robot Model/Controller": "W833",
        "Part Family": "DEMO-PN-1200 - Demo housing cap",
        "Part Name/Description": "Demo housing cap",
        "EOAT Type": "Vacuum",
        "Connection Type": "Direct Mount",
        "Cleanroom/Non-Cleanroom": "Cleanroom",
        "Cup Type/Material": "Silicone",
        "Gripper Model": "Zimmer GPP",
        "Gripper Size": "25 mm",
        "Tubing Condition": "OK",
        "Cable Management Condition": "OK",
        "Known Issues": "Original known issue.",
        "Photos Taken?": "Yes",
        "Photo Folder/Link": "01_EOAT_Audit/Cell_Photos/Overall/original",
        "Status": "Complete",
        "Priority": "Medium",
        "Follow-Up Needed": "No",
        "Notes": "Original notes.",
    }
    entry.update(overrides)
    result = save_audit_entry(project_root, entry)
    assert result.success, result.errors
    return entry


def test_save_complete_and_optional_missing_audit_entries(qapp, fake_config, fake_project, frozen_project_date):
    page = AuditPage(fake_config)
    page.show()

    complete_values = {
        "Auditor": "Usability Tester",
        "Plant/Area": "Plant 4",
        "Press/Machine #": "Press 104",
        "Robot Type": "Wittmann R9",
        "Robot Model/Controller": "Wittmann synthetic",
        "Part Family": "Part family D",
        "EOAT Type": "Vacuum",
        "Connection Type": "ATI",
        "Tubing Condition": "OK",
        "Cable Management Condition": "OK",
        "Known Issues": "No issue found during fake test.",
        "Photos Taken?": "Yes",
        "Status": "Complete",
        "Priority": "Medium",
        "Follow-Up Needed": "No",
        "Notes": "Complete audit entry from usability test.",
    }
    for field, value in complete_values.items():
        _set_field(page, field, value)
    complete_id = page.audit_fields["Audit ID"].text()
    click_button(page, "Save Audit Entry")
    wait_for_background_tasks()

    rows = row_dicts(fake_project / "01_EOAT_Audit" / "EOAT_Audit_Database" / "EOAT_Master_Tracker.xlsx", "EOAT Inventory")
    assert any(row["Audit ID"] == complete_id and row["Press/Machine #"] == "Press 104" for row in rows)
    saved_row = next(row for row in rows if row["Audit ID"] == complete_id)
    assert saved_row["Connection Type"] == "ATI"
    assert saved_row["Cup Type/Material"] == "Silicone"
    assert saved_row["Cleanroom/Non-Cleanroom"] == "Whiteroom"
    assert saved_row["Gripper Model"] == "N/A"
    assert saved_row["Notes"] == "Complete audit entry from usability test."
    assert "Saved audit entry" in page.result_panel.viewer.toPlainText()

    page.clear_audit_form()
    for field, value in {
        "Auditor": "Usability Tester",
        "Plant/Area": "Plant 4",
        "Press/Machine #": "Press 105",
        "Robot Type": "Engel Viper",
        "EOAT Type": "Mechanical / Gripper",
    }.items():
        _set_field(page, field, value)
    optional_missing_id = page.audit_fields["Audit ID"].text()
    click_button(page, "Save Audit Entry")
    wait_for_background_tasks()
    rows = row_dicts(fake_project / "01_EOAT_Audit" / "EOAT_Audit_Database" / "EOAT_Master_Tracker.xlsx", "EOAT Inventory")
    assert any(row["Audit ID"] == optional_missing_id and row["Press/Machine #"] == "Press 105" for row in rows)
    optional_row = next(row for row in rows if row["Audit ID"] == optional_missing_id)
    assert optional_row["Cleanroom/Non-Cleanroom"] == "Whiteroom"
    assert optional_row["Cup Type/Material"] == "N/A"
    assert optional_row["Cup Diameter/Size"] == "N/A"
    assert optional_row["Number of Vacuum Cups"] == "N/A"
    assert optional_row["Connection Type"] == "N/A"
    assert optional_row["Known Issues"] == "N/A"

    activity_log = fake_project / "00_Project_Admin" / "Activity_Logs" / "activity_log.jsonl"
    entries = [json.loads(line) for line in activity_log.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert any(entry["tool_id"] == "eoat_audit_form" and entry["success"] for entry in entries)


def test_invalid_audit_entry_shows_friendly_error_without_workbook_row(qapp, fake_config, fake_project, frozen_project_date):
    page = AuditPage(fake_config)
    page.show()
    page.clear_audit_form()
    bad_id = page.audit_fields["Audit ID"].text()
    _set_field(page, "Auditor", "")
    _set_field(page, "Plant/Area", "Plant 4")
    _set_field(page, "Press/Machine #", "Press BAD")
    _set_field(page, "Robot Type", "")
    _set_field(page, "EOAT Type", "")

    click_button(page, "Save Audit Entry")
    wait_for_background_tasks()
    text = page.result_panel.viewer.toPlainText()
    assert "Audit entry failed validation" in text
    assert "Missing required field" in text
    rows = row_dicts(fake_project / "01_EOAT_Audit" / "EOAT_Audit_Database" / "EOAT_Master_Tracker.xlsx", "EOAT Inventory")
    assert all(row["Audit ID"] != bad_id for row in rows)


def test_duplicate_audit_creates_new_unsaved_copy_and_saves_without_overwriting_original(qapp, fake_config, fake_project, frozen_project_date):
    original = _seed_audit(fake_project, "AUD-DUP-SOURCE-001")
    page = AuditPage(fake_config)
    page.show()

    page.load_audit_id_edit.setText(original["Audit ID"])
    click_button(page, "Load Existing Audit ID")
    click_button(page, "Duplicate Audit")

    duplicate_id = page.audit_fields["Audit ID"].text()
    assert duplicate_id != original["Audit ID"]
    assert page.audit_fields["Audit Date"].text() == "2026-05-19"
    assert page.audit_fields["Press/Machine #"].text() == original["Press/Machine #"]
    assert page.audit_fields["Tool #"].text() == original["Tool #"]
    assert page.audit_fields["Connection Type"].currentText() == original["Connection Type"]
    assert page.audit_fields["Cleanroom/Non-Cleanroom"].currentText() == original["Cleanroom/Non-Cleanroom"]
    assert page.audit_fields["Cup Type/Material"].text() == original["Cup Type/Material"]
    assert page.audit_fields["Gripper Model"].text() == original["Gripper Model"]
    assert page.audit_fields["Gripper Size"].text() == original["Gripper Size"]
    assert page.audit_fields["Photo Folder/Link"].text() == ""
    assert "new unsaved" in page.lookup_note_label.text()

    _set_field(page, "Notes", "Duplicated audit notes.")
    click_button(page, "Save Audit Entry")
    wait_for_background_tasks()

    rows = row_dicts(fake_project / "01_EOAT_Audit" / "EOAT_Audit_Database" / "EOAT_Master_Tracker.xlsx", "EOAT Inventory")
    original_row = next(row for row in rows if row["Audit ID"] == original["Audit ID"])
    duplicate_row = next(row for row in rows if row["Audit ID"] == duplicate_id)
    assert original_row["Notes"] == original["Notes"]
    assert original_row["Photo Folder/Link"] == original["Photo Folder/Link"]
    assert duplicate_row["Notes"] == "Duplicated audit notes."
    assert duplicate_row["Connection Type"] == original["Connection Type"]
    assert duplicate_row["Cleanroom/Non-Cleanroom"] == original["Cleanroom/Non-Cleanroom"]
    assert duplicate_row["Cup Type/Material"] == original["Cup Type/Material"]
    assert duplicate_row["Gripper Model"] == original["Gripper Model"]
    assert duplicate_row["Gripper Size"] == original["Gripper Size"]
    assert duplicate_row["Photo Folder/Link"] == "N/A"


def test_load_and_duplicate_audit_with_na_values(qapp, fake_config, fake_project, frozen_project_date):
    original = _seed_audit(
        fake_project,
        "AUD-DUP-NA-001",
        **{
            "Connection Type": "",
            "Known Issues": "",
            "Gripper Model": "",
            "Gripper Size": "",
        },
    )
    page = AuditPage(fake_config)
    page.show()

    page.load_audit_id_edit.setText(original["Audit ID"])
    click_button(page, "Load Existing Audit ID")

    assert page.audit_fields["Connection Type"].currentText() == ""
    assert page.audit_fields["Known Issues"].toPlainText() == ""
    assert page.audit_fields["Gripper Model"].text() == ""

    click_button(page, "Duplicate Audit")
    assert page.audit_fields["Connection Type"].currentText() == ""
    assert page.audit_fields["Known Issues"].toPlainText() == ""
    assert page.audit_fields["Gripper Model"].text() == ""
    duplicate_id = page.audit_fields["Audit ID"].text()
    click_button(page, "Save Audit Entry")
    wait_for_background_tasks()

    rows = row_dicts(fake_project / "01_EOAT_Audit" / "EOAT_Audit_Database" / "EOAT_Master_Tracker.xlsx", "EOAT Inventory")
    duplicate_row = next(row for row in rows if row["Audit ID"] == duplicate_id)
    assert duplicate_row["Connection Type"] == "N/A"
    assert duplicate_row["Known Issues"] == "N/A"
    assert duplicate_row["Gripper Model"] == "N/A"
    assert duplicate_row["Gripper Size"] == "N/A"


def test_loaded_na_field_displays_blank_and_can_be_filled(qapp, fake_config, fake_project, frozen_project_date):
    original = _seed_audit(fake_project, "AUD-LOAD-NA-001", **{"Known Issues": "", "Gripper Model": ""})
    page = AuditPage(fake_config)
    page.show()

    page.load_audit_id_edit.setText(original["Audit ID"])
    click_button(page, "Load Existing Audit ID")

    assert page.audit_fields["Known Issues"].toPlainText() == ""
    assert page.audit_fields["Gripper Model"].text() == ""

    _set_field(page, "Known Issues", "Added after review.")
    _set_field(page, "Gripper Model", "Zimmer GPP")
    click_button(page, "Save Audit Entry")
    wait_for_background_tasks()

    rows = row_dicts(fake_project / "01_EOAT_Audit" / "EOAT_Audit_Database" / "EOAT_Master_Tracker.xlsx", "EOAT Inventory")
    updated_row = next(row for row in rows if row["Audit ID"] == original["Audit ID"])
    assert updated_row["Known Issues"] == "Added after review."
    assert updated_row["Gripper Model"] == "Zimmer GPP"


def test_loaded_blank_workbook_values_display_blank_and_save_na(qapp, fake_config, fake_project, frozen_project_date):
    original = _seed_audit(fake_project, "AUD-LOAD-BLANK-001")
    workbook_path = fake_project / "01_EOAT_Audit" / "EOAT_Audit_Database" / "EOAT_Master_Tracker.xlsx"
    workbook = load_workbook(workbook_path)
    ws = workbook["EOAT Inventory"]
    headers = [cell.value for cell in ws[1]]
    row_number = next(row for row in range(2, ws.max_row + 1) if ws.cell(row=row, column=headers.index("Audit ID") + 1).value == original["Audit ID"])
    ws.cell(row=row_number, column=headers.index("Known Issues") + 1).value = None
    ws.cell(row=row_number, column=headers.index("Gripper Model") + 1).value = ""
    workbook.save(workbook_path)
    workbook.close()

    page = AuditPage(fake_config)
    page.show()
    page.load_audit_id_edit.setText(original["Audit ID"])
    click_button(page, "Load Existing Audit ID")

    assert page.audit_fields["Known Issues"].toPlainText() == ""
    assert page.audit_fields["Gripper Model"].text() == ""

    click_button(page, "Save Audit Entry")
    wait_for_background_tasks()

    rows = row_dicts(workbook_path, "EOAT Inventory")
    updated_row = next(row for row in rows if row["Audit ID"] == original["Audit ID"])
    assert updated_row["Known Issues"] == "N/A"
    assert updated_row["Gripper Model"] == "N/A"


def test_hidden_tooling_values_are_saved_when_switching_eoat_type(qapp, fake_config, fake_project, frozen_project_date):
    page = AuditPage(fake_config)
    page.show()

    _set_field(page, "Auditor", "Usability Tester")
    _set_field(page, "Plant/Area", "Plant 4")
    _set_field(page, "Press/Machine #", "Press 106")
    _set_field(page, "Robot Type", "Wittmann R9")
    _set_field(page, "EOAT Type", "Hybrid")
    _set_field(page, "Connection Type", "ATI")
    _set_field(page, "Cup Type/Material", "Nitrile")
    _set_field(page, "Cup Diameter/Size", "20 mm")
    _set_field(page, "Gripper Model", "Zimmer GPP")
    _set_field(page, "Gripper Size", "25 mm")
    _set_field(page, "EOAT Type", "Mechanical / Gripper")

    audit_id = page.audit_fields["Audit ID"].text()
    click_button(page, "Save Audit Entry")
    wait_for_background_tasks()

    rows = row_dicts(fake_project / "01_EOAT_Audit" / "EOAT_Audit_Database" / "EOAT_Master_Tracker.xlsx", "EOAT Inventory")
    row = next(row for row in rows if row["Audit ID"] == audit_id)
    assert row["EOAT Type"] == "Mechanical / Gripper"
    assert row["Cup Type/Material"] == "Nitrile"
    assert row["Cup Diameter/Size"] == "20 mm"
    assert row["Gripper Model"] == "Zimmer GPP"
    assert row["Gripper Size"] == "25 mm"


def test_duplicate_audit_can_change_press_and_autofill_tool_from_new_part_number(qapp, fake_config, fake_project, frozen_project_date):
    create_press_reference_workbooks(fake_project / "reference-data")
    original = _seed_audit(fake_project, "AUD-DUP-AUTOFILL-001")
    page = AuditPage(fake_config)

    page.load_audit_id_edit.setText(original["Audit ID"])
    click_button(page, "Load Existing Audit ID")
    click_button(page, "Duplicate Audit")
    duplicate_id = page.audit_fields["Audit ID"].text()

    page.audit_fields["Press/Machine #"].setText("Press 70")
    page.audit_fields["Press/Machine #"].editingFinished.emit()
    assert page.audit_fields["Press/Machine #"].text() == "70"
    assert page.audit_fields["Tool #"].text() == "DEMO-PN-0170"

    click_button(page, "Save Audit Entry")
    wait_for_background_tasks()

    rows = row_dicts(fake_project / "01_EOAT_Audit" / "EOAT_Audit_Database" / "EOAT_Master_Tracker.xlsx", "EOAT Inventory")
    duplicate_row = next(row for row in rows if row["Audit ID"] == duplicate_id)
    original_row = next(row for row in rows if row["Audit ID"] == original["Audit ID"])
    assert duplicate_row["Press/Machine #"] == "70"
    assert duplicate_row["Tool #"] == "DEMO-PN-0170"
    assert original_row["Press/Machine #"] == original["Press/Machine #"]
    assert original_row["Tool #"] == original["Tool #"]


def test_manual_audit_id_change_saves_new_row_and_existing_id_collision_is_blocked(qapp, fake_config, fake_project, frozen_project_date):
    original = _seed_audit(fake_project, "AUD-MANUAL-SOURCE-001", Notes="Keep original.")
    other = _seed_audit(fake_project, "AUD-MANUAL-EXISTING-002")
    page = AuditPage(fake_config)

    page.load_audit_id_edit.setText(original["Audit ID"])
    click_button(page, "Load Existing Audit ID")
    _set_field(page, "Audit ID", "AUD-MANUAL-NEW")
    _set_field(page, "Press/Machine #", "Press 200")
    _set_field(page, "Tool #", "PN-2000")
    _set_field(page, "Notes", "Manual save-as row.")
    click_button(page, "Save Audit Entry")
    wait_for_background_tasks()

    rows = row_dicts(fake_project / "01_EOAT_Audit" / "EOAT_Audit_Database" / "EOAT_Master_Tracker.xlsx", "EOAT Inventory")
    assert next(row for row in rows if row["Audit ID"] == original["Audit ID"])["Notes"] == "Keep original."
    manual_row = next(row for row in rows if row["Audit ID"] == "AUD-MANUAL-NEW")
    assert manual_row["Press/Machine #"] == "Press 200"
    assert manual_row["Tool #"] == "PN-2000"

    page.load_audit_id_edit.setText(original["Audit ID"])
    click_button(page, "Load Existing Audit ID")
    _set_field(page, "Audit ID", other["Audit ID"])
    _set_field(page, "Notes", "Should not overwrite existing row.")
    click_button(page, "Save Audit Entry")
    wait_for_background_tasks()

    rows = row_dicts(fake_project / "01_EOAT_Audit" / "EOAT_Audit_Database" / "EOAT_Master_Tracker.xlsx", "EOAT Inventory")
    other_row = next(row for row in rows if row["Audit ID"] == other["Audit ID"])
    assert other_row["Notes"] == other["Notes"]
    assert "Audit ID already exists" in page.result_panel.viewer.toPlainText()
    headers = set(rows[0].keys())
    assert "Setup ID" not in headers
    assert "Tool-Press Map" not in workbook_sheet_names(fake_project / "01_EOAT_Audit" / "EOAT_Audit_Database" / "EOAT_Master_Tracker.xlsx")

