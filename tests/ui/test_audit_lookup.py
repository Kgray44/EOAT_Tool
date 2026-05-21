from __future__ import annotations

import pytest
from PySide6.QtWidgets import QComboBox, QLabel, QLineEdit, QTextEdit

from app.pages.audit import AuditPage
from core.tool_fields import LEGACY_TOOL_FIELD
from core.workbook_io import row_dicts
from core.workbook_schema import get_expected_headers
from tests.fixtures.reference_workbooks import create_press_reference_workbooks
from tests.ui.helpers import click_button, wait_for_background_tasks


pytestmark = pytest.mark.usability


REFERENCE_ONLY_FIELDS = {
    "U.S. Tons",
    "Press Brand",
    "Press Model",
    "Press Tonnage",
    "Press Year",
    "Injection Pressure",
    "Injection Capacity",
    "Screw Diameter",
    "Controller Type",
    "Robot Serial Number",
    "Robot Manufacturing Date",
    "Full Servo",
    "TCU Count",
    "EDART Unit Press Side",
    "Forecasted Capacity",
    "Available Capacity",
    "Hours Allocated per Month",
    "Hours per Week",
    "Committed Hours per Year",
    "Cycle Time (S)",
    "Cavitation",
}


def _combo_items(combo: QComboBox) -> list[str]:
    return [combo.itemText(index) for index in range(combo.count())]


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


def test_auditor_and_plant_defaults(qapp, fake_config):
    page = AuditPage(fake_config)

    assert page.audit_fields["Auditor"].text() == "Kato Gray"
    assert page.audit_fields["Known Issues"].toPlainText() == "None"
    assert page.audit_fields["Drop/Mis-Pick History"].toPlainText() == "None"
    assert page.audit_fields["Maintenance Frequency"].text() == "None"
    assert page.audit_fields["Cleanroom/Non-Cleanroom"].currentText() == "Whiteroom"
    assert page.audit_fields["Cup Type/Material"].text() == "Silicone"
    plant = page.audit_fields["Plant/Area"]
    assert isinstance(plant, QComboBox)
    assert plant.isEditable() is False
    assert _combo_items(plant) == ["Plant 4", "Cleanroom"]
    assert plant.currentText() == "Plant 4"
    assert page.audit_fields["Vacuum Confirmation Present?"].currentText() == "Yes"
    assert page.audit_fields["Part-Present Detection Present?"].currentText() == "No"
    assert page.audit_fields["Spare Parts Identified?"].currentText() == "No"
    assert page.audit_fields["Drawing/CAD Available?"].currentText() == "No"
    assert page.audit_fields["BOM Available?"].currentText() == "No"
    assert page.audit_fields["Process Binder Complete?"].currentText() == "No"
    assert page.audit_fields["Photos Taken?"].currentText() == "No"


def test_audit_page_does_not_show_reference_spreadsheet_fields(qapp, fake_config):
    page = AuditPage(fake_config)

    assert REFERENCE_ONLY_FIELDS.isdisjoint(page.audit_fields)
    workflow_metadata = {"Entry Type", "Source Audit ID", "Compatibility Source"}
    assert (set(get_expected_headers("EOAT Inventory")) - workflow_metadata).issubset(page.audit_fields)
    assert {"Tool #", "Connection Type", "Gripper Model", "Gripper Size", "Number of Vacuum Cups", "Tubing Condition", "Cable Management Condition", "BOM Available?", "Photos Taken?"}.issubset(page.audit_fields)
    assert LEGACY_TOOL_FIELD not in page.audit_fields
    label_texts = {label.text() for label in page.findChildren(QLabel)}
    assert "Tool #" in label_texts
    assert "Connection Type" in label_texts
    assert LEGACY_TOOL_FIELD not in label_texts


def test_connection_type_and_eoat_type_dropdown_options(qapp, fake_config):
    page = AuditPage(fake_config)

    eoat_moves = page.audit_fields["EOAT Moves"]
    assert isinstance(eoat_moves, QComboBox)
    assert eoat_moves.isEditable() is False
    assert _combo_items(eoat_moves) == ["", "Part", "Sprue", "Both"]
    assert eoat_moves.currentText() == ""

    connection = page.audit_fields["Connection Type"]
    assert isinstance(connection, QComboBox)
    assert connection.isEditable() is False
    assert _combo_items(connection) == ["ATI", "DoveTail", "Direct Mount", "Lever Lock"]
    assert connection.currentText() == ""

    eoat_type = page.audit_fields["EOAT Type"]
    assert isinstance(eoat_type, QComboBox)
    assert "Miscellaneous" in _combo_items(eoat_type)

    cleanroom = page.audit_fields["Cleanroom/Non-Cleanroom"]
    assert isinstance(cleanroom, QComboBox)
    assert "Whiteroom" in _combo_items(cleanroom)

    tooling_fields = list(page.audit_fields)
    assert tooling_fields.index("EOAT Type") < tooling_fields.index("EOAT Moves") < tooling_fields.index("Connection Type") < tooling_fields.index("Cup Type/Material") < tooling_fields.index("Gripper Model") < tooling_fields.index("Gripper Size")


@pytest.mark.parametrize(
    ("eoat_type", "vacuum_visible", "gripper_visible"),
    [
        ("Vacuum", True, False),
        ("Mechanical / Gripper", False, True),
        ("Hybrid", True, True),
        ("Unknown / Needs Review", True, True),
        ("Miscellaneous", True, True),
    ],
)
def test_eoat_type_controls_tooling_visibility(qapp, fake_config, eoat_type, vacuum_visible, gripper_visible):
    page = AuditPage(fake_config)

    _set_field(page, "EOAT Type", eoat_type)

    assert page.audit_fields["Cup Type/Material"].isHidden() is (not vacuum_visible)
    assert page.audit_fields["Cup Diameter/Size"].isHidden() is (not vacuum_visible)
    assert page.audit_fields["Number of Vacuum Cups"].isHidden() is (not vacuum_visible)
    assert page.audit_fields["Gripper Model"].isHidden() is (not gripper_visible)
    assert page.audit_fields["Gripper Size"].isHidden() is (not gripper_visible)
    assert page.audit_fields["Gripper Type"].isHidden() is (not gripper_visible)


def test_eoat_type_visibility_updates_immediately_and_preserves_hidden_values(qapp, fake_config):
    page = AuditPage(fake_config)

    _set_field(page, "EOAT Type", "Hybrid")
    _set_field(page, "Cup Type/Material", "Nitrile")
    _set_field(page, "Cup Diameter/Size", "20 mm")
    _set_field(page, "Gripper Model", "Zimmer GPP")
    _set_field(page, "Gripper Size", "25 mm")
    _set_field(page, "EOAT Type", "Mechanical / Gripper")

    assert page.audit_fields["Cup Type/Material"].isHidden() is True
    assert page.audit_fields["Cup Diameter/Size"].isHidden() is True
    assert page.audit_fields["Gripper Model"].isHidden() is False
    assert page.audit_fields["Gripper Size"].isHidden() is False
    assert page.audit_fields["Cup Type/Material"].text() == "Nitrile"
    assert page.audit_fields["Cup Diameter/Size"].text() == "20 mm"

    _set_field(page, "EOAT Type", "Vacuum")
    assert page.audit_fields["Gripper Model"].isHidden() is True
    assert page.audit_fields["Gripper Size"].isHidden() is True
    assert page.audit_fields["Gripper Model"].text() == "Zimmer GPP"
    assert page.audit_fields["Gripper Size"].text() == "25 mm"


def test_sensors_present_controls_sensor_electrical_visibility(qapp, fake_config):
    page = AuditPage(fake_config)

    _set_field(page, "Sensor Type", "Vacuum switch")
    _set_field(page, "Sensor Brand/Model", "SMC ZSE20")
    _set_field(page, "Electrical Quick Disconnect Type", "M12")
    _set_field(page, "Cable Management Condition", "OK")
    _set_field(page, "Sensors Present?", "No")

    for field in [
        "Sensor Type",
        "Sensor Brand/Model",
        "Vacuum Confirmation Present?",
        "Part-Present Detection Present?",
    ]:
        assert page.audit_fields[field].isHidden() is True
    assert page.audit_fields["Electrical Quick Disconnect Type"].isHidden() is False
    assert page.audit_fields["Cable Management Condition"].isHidden() is False

    assert page.audit_fields["Known Issues"].isHidden() is False
    _set_field(page, "Known Issues", "Unrelated value survives.")

    _set_field(page, "Sensors Present?", "Yes")

    for field in [
        "Sensor Type",
        "Sensor Brand/Model",
        "Vacuum Confirmation Present?",
        "Part-Present Detection Present?",
    ]:
        assert page.audit_fields[field].isHidden() is False
    assert page.audit_fields["Sensor Type"].text() == "Vacuum switch"
    assert page.audit_fields["Sensor Brand/Model"].text() == "SMC ZSE20"
    assert page.audit_fields["Electrical Quick Disconnect Type"].text() == "M12"
    assert page.audit_fields["Cable Management Condition"].currentText() == "OK"
    assert page.audit_fields["Known Issues"].toPlainText() == "Unrelated value survives."


def test_ui_lookup_runs_on_editing_finished_and_fills_clean_fields(qapp, fake_config, fake_project):
    create_press_reference_workbooks(fake_project / "reference-data")
    page = AuditPage(fake_config)
    page.show()

    page.audit_fields["Press/Machine #"].setText("P12")
    page.audit_fields["Press/Machine #"].editingFinished.emit()

    assert page.audit_fields["Press/Machine #"].text() == "12"
    assert page.audit_fields["Robot Type"].currentText() == "Wittmann W833"
    assert page.audit_fields["Robot Model/Controller"].text() == "W833"
    assert page.audit_fields["Tool #"].text() == "DEMO-PN-1200"
    assert page.audit_fields["Part Family"].text() == "DEMO-PN-1200 - Demo housing cap"
    assert page.audit_fields["Part Name/Description"].toPlainText() == "Demo housing cap"
    assert "Robot and part info filled" in page.lookup_note_label.text()


def test_manual_lookup_button_uses_same_lookup_path(qapp, fake_config, fake_project):
    create_press_reference_workbooks(fake_project / "reference-data")
    page = AuditPage(fake_config)

    page.audit_fields["Press/Machine #"].setText("Press #12")
    click_button(page, "Lookup")

    assert page.audit_fields["Press/Machine #"].text() == "12"
    assert page.audit_fields["Robot Type"].currentText() == "Wittmann W833"


def test_multiple_capacity_rows_show_selector_without_autofilling_part(qapp, fake_config, fake_project):
    create_press_reference_workbooks(fake_project / "reference-data", multiple_capacity_rows=True)
    page = AuditPage(fake_config)

    page.audit_fields["Press/Machine #"].setText("Machine 12")
    page.audit_fields["Press/Machine #"].editingFinished.emit()

    assert page.capacity_part_combo.isEnabled()
    assert page.capacity_part_combo.count() == 3
    assert page.capacity_matches_table.rowCount() == 2
    assert "possible parts" in page.lookup_note_label.text()
    assert "Multiple possible Tool # values found for this press" in page.lookup_note_label.text()
    assert page.audit_fields["Tool #"].text() == ""
    assert page.audit_fields["Part Family"].text() == ""

    page.capacity_part_combo.setCurrentIndex(2)
    assert page.audit_fields["Tool #"].text() == "DEMO-PN-1201"
    assert page.audit_fields["Part Family"].text() == "DEMO-PN-1201 - Demo housing base"
    assert page.audit_fields["Part Name/Description"].toPlainText() == "Demo housing base"


def test_missing_machine_number_lookup_does_not_crash(qapp, fake_config):
    page = AuditPage(fake_config)

    page.audit_fields["Press/Machine #"].setText("")
    page.audit_fields["Press/Machine #"].editingFinished.emit()

    assert "Invalid machine number" in page.lookup_note_label.text()


def test_save_writes_clean_audit_fields_not_reference_values(qapp, fake_config, fake_project, frozen_project_date):
    create_press_reference_workbooks(fake_project / "reference-data")
    page = AuditPage(fake_config)
    page.show()

    page.audit_fields["Press/Machine #"].setText("P12")
    page.audit_fields["Press/Machine #"].editingFinished.emit()
    _set_field(page, "EOAT Type", "Vacuum")
    _set_field(page, "Sensors Present?", "Yes")
    _set_field(page, "Vacuum Confirmation Present?", "Yes")
    _set_field(page, "Quick Disconnects Present?", "Unknown / Not Checked")
    _set_field(page, "Tubing Condition", "OK")
    _set_field(page, "Known Issues", "No issue during test.")
    _set_field(page, "Notes", "Clean form save test.")

    audit_id = page.audit_fields["Audit ID"].text()
    click_button(page, "Save Audit Entry")
    wait_for_background_tasks()

    rows = row_dicts(fake_project / "01_EOAT_Audit" / "EOAT_Audit_Database" / "EOAT_Master_Tracker.xlsx", "EOAT Inventory")
    row = next(row for row in rows if row["Audit ID"] == audit_id)
    assert row["Auditor"] == "Kato Gray"
    assert row["Plant/Area"] == "Plant 4"
    assert row["Press/Machine #"] == "12"
    assert row["Tool #"] == "DEMO-PN-1200"
    assert row["Robot Type"] == "Wittmann W833"
    assert row["Robot Model/Controller"] == "W833"
    assert row["Part Family"] == "DEMO-PN-1200 - Demo housing cap"
    assert row["Part Name/Description"] == "Demo housing cap"
    assert row["Sensors Present?"] == "Yes"
    assert row["Vacuum Confirmation Present?"] == "Yes"
    assert row["Quick Disconnects Present?"] == "Unknown / Not Checked"
    assert row["Tubing Condition"] == "OK"
    assert row["Notes"] == "Clean form save test."
    for field in REFERENCE_ONLY_FIELDS:
        assert field not in row or row[field] in ("", None)


def test_lookup_does_not_overwrite_manual_robot_type(qapp, fake_config, fake_project):
    create_press_reference_workbooks(fake_project / "reference-data")
    page = AuditPage(fake_config)

    page.audit_fields["Robot Type"].setEditText("Manual robot")
    page.audit_fields["Press/Machine #"].setText("12")
    page.audit_fields["Press/Machine #"].editingFinished.emit()

    assert page.audit_fields["Robot Type"].currentText() == "Manual robot"
    assert "different Robot Type suggestion" in page.lookup_note_label.text()


def test_lookup_does_not_overwrite_manual_tool_number(qapp, fake_config, fake_project):
    create_press_reference_workbooks(fake_project / "reference-data")
    page = AuditPage(fake_config)

    page.audit_fields["Tool #"].setText("MANUAL-TOOL")
    page.audit_fields["Press/Machine #"].setText("12")
    page.audit_fields["Press/Machine #"].editingFinished.emit()

    assert page.audit_fields["Tool #"].text() == "MANUAL-TOOL"
    assert "different Tool # suggestion" in page.lookup_note_label.text()

