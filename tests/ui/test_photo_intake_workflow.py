from __future__ import annotations

import json

import pytest
from PySide6.QtWidgets import QTableWidgetItem, QWidget

from app.pages.photos import PhotosPage
from core.audit_field_links import build_audit_field_link, serialize_audit_field_link
from core.workbook_io import row_dicts
from tests.ui.helpers import click_button, wait_for_background_tasks

pytestmark = pytest.mark.usability


def _combo_data_values(combo) -> set[str]:
    return {str(combo.itemData(index) or "") for index in range(combo.count())}


class _LinkHost(QWidget):
    def __init__(self):
        super().__init__()
        self.opened_link = ""

    def navigate_to_audit_field_link(self, link_text: str) -> bool:
        self.opened_link = link_text
        return True


def _sample_link() -> str:
    link = build_audit_field_link(
        {
            "Audit ID": "AUD-20260518-001",
            "Press/Machine #": "Press 101",
            "Tool #": "TOOL-A",
        },
        "Tubing Routing Notes",
        "Tubing Routing Notes",
        created_at="2026-06-02T12:00:00+00:00",
    )
    return serialize_audit_field_link(link)


def test_photo_intake_previews_copies_and_indexes_selected_images(qapp, fake_config, fake_project, frozen_project_date):
    page = PhotosPage(fake_config)
    page.show()

    click_button(page, "Refresh Incoming Photos")
    assert page.incoming_list.count() >= 2
    page.incoming_list.item(0).setSelected(True)
    page.incoming_list.item(1).setSelected(True)
    page.plant_edit.setText("Molding")
    page.press_edit.setText("Press 101")
    page.tool_edit.setText("6200171020")
    page.date_edit.setText("2026-05-19")
    page.view_combo.setCurrentText("Vacuum Cups / Grippers")
    page.audit_id_edit.setText("AUD-20260518-001")
    page.description_edit.setPlainText("Fake intake usability photos.")
    page.notes_edit.setPlainText("No real internship image files used.")

    click_button(page, "Preview Rename/Move")
    preview_text = page.result_panel.viewer.toPlainText()
    assert "Molding_Machine101_Tool6200171020_EOAT_2026-05-19_VacuumCupsGrippers" in preview_text

    click_button(page, "Confirm Intake")
    wait_for_background_tasks()

    target_dir = fake_project / "01_EOAT_Audit" / "Cell_Photos" / "Vacuum_Cups_Grippers"
    copied = list(target_dir.glob("Molding_Machine101_Tool6200171020_EOAT_2026-05-19_VacuumCupsGrippers_*"))
    assert len(copied) == 2
    rows = row_dicts(fake_project / "01_EOAT_Audit" / "EOAT_Audit_Database" / "EOAT_Master_Tracker.xlsx", "Photo Index")
    assert sum(1 for row in rows if row["Related Audit ID"] == "AUD-20260518-001") >= 2

    activity_log = fake_project / "00_Project_Admin" / "Activity_Logs" / "activity_log.jsonl"
    entries = [json.loads(line) for line in activity_log.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert any(entry["tool_id"] == "photo_intake" and entry["success"] for entry in entries)


def test_photos_page_related_audit_and_issue_fields_are_dropdowns(qapp, usability_fake_config):
    from PySide6.QtWidgets import QComboBox

    page = PhotosPage(usability_fake_config)
    page.show()

    assert isinstance(page.audit_id_edit, QComboBox)
    assert isinstance(page.issue_id_edit, QComboBox)
    assert {"AUD-20260518-001", "AUD-20260518-002", "AUD-20260518-003"}.issubset(
        _combo_data_values(page.audit_id_edit)
    )
    assert {"ISS-001", "ISS-002", "ISS-003"}.issubset(_combo_data_values(page.issue_id_edit))

    page.audit_id_edit.setCurrentIndex(page.audit_id_edit.findData("AUD-20260518-002"))
    page.issue_id_edit.setCurrentIndex(page.issue_id_edit.findData("ISS-002"))

    metadata = page.metadata()
    assert metadata["related_audit_id"] == "AUD-20260518-002"
    assert metadata["related_issue_id"] == "ISS-002"


def test_photos_page_receives_pending_audit_field_link(qapp, usability_fake_config):
    page = PhotosPage(usability_fake_config)
    page.show()
    link_text = _sample_link()

    page.apply_pending_audit_field_link(link_text)

    assert page.audit_field_link_edit.text() == link_text
    assert page.audit_id_edit.text() == "AUD-20260518-001"
    assert page.tool_edit.text() == "TOOL-A"
    assert "Field: Tubing Routing Notes" in page.link_display_label.text()
    assert page.go_to_link_button.isEnabled()


def test_photos_page_go_to_link_uses_navigation_host(qapp, usability_fake_config):
    host = _LinkHost()
    page = PhotosPage(usability_fake_config, parent=host)
    page.show()
    link_text = _sample_link()
    page.apply_pending_audit_field_link(link_text)

    click_button(page, "Go to Link")

    assert host.opened_link == link_text


def test_photos_page_go_to_link_uses_selected_indexed_photo_row(qapp, usability_fake_config):
    host = _LinkHost()
    page = PhotosPage(usability_fake_config, parent=host)
    page.show()
    link_text = _sample_link()
    page.audit_field_link_edit.clear()
    page.indexed_photos_table.setRowCount(1)
    page.indexed_photos_table.setItem(0, 0, QTableWidgetItem("PHO-LINK-001"))
    page.indexed_photos_table.setItem(0, 4, QTableWidgetItem(link_text))
    page.indexed_photos_table.setCurrentCell(0, 4)
    page._update_go_to_link_button()

    click_button(page, "Go to Link")

    assert host.opened_link == link_text


def test_photos_page_invalid_and_legacy_links_are_unavailable(qapp, usability_fake_config):
    page = PhotosPage(usability_fake_config)
    page.show()
    page.audit_field_link_edit.setText("Machine 12 - Tubing Routing Notes")

    assert not page.go_to_link_button.isEnabled()

    page.go_to_audit_field_link()

    assert "unavailable" in page.result_panel.viewer.toPlainText()


def test_photo_intake_empty_incoming_folder_has_helpful_empty_state(qapp, fake_config, fake_project):
    incoming = fake_project / "01_EOAT_Audit" / "Cell_Photos" / "Incoming_Photos"
    for path in incoming.iterdir():
        path.unlink()

    page = PhotosPage(fake_config)
    page.show()
    click_button(page, "Refresh Incoming Photos")

    assert page.incoming_list.count() == 0
    assert "No incoming photos found" in page.empty_hint.text()
    assert "Incoming_Photos" in page.result_panel.viewer.toPlainText()


def test_photos_page_audit_lookup_autofill_and_next_missing_shot(
    qapp, usability_fake_config, usability_fake_project
):
    page = PhotosPage(usability_fake_config)
    page.show()

    target_index = -1
    for index in range(page.audit_lookup_combo.count()):
        if "AUD-20260518-002" in page.audit_lookup_combo.itemText(index):
            target_index = index
            break
    assert target_index > 0

    page.audit_lookup_combo.setCurrentIndex(target_index)

    assert page.audit_id_edit.text() == "AUD-20260518-002"
    assert page.press_edit.text() == "Press 102"
    assert page.tool_edit.text() == "TOOL-B"
    assert "Tool #: TOOL-B" in page.audit_context_label.text()
    assert "Gripper Size" not in page.audit_context_label.text()

    click_button(page, "Use Next Missing Shot Type")

    assert page.view_combo.currentText() in {"Overall EOAT", "Tool Connection", "Grippers", "Tool Label / ID Plate"}


def test_photos_page_preserves_manually_entered_tool_number(qapp, usability_fake_config):
    page = PhotosPage(usability_fake_config)
    page.show()
    page.tool_edit.setText("MANUAL-TOOL")

    target_index = -1
    for index in range(page.audit_lookup_combo.count()):
        if "AUD-20260518-002" in page.audit_lookup_combo.itemText(index):
            target_index = index
            break
    assert target_index > 0

    page.audit_lookup_combo.setCurrentIndex(target_index)

    assert page.tool_edit.text() == "MANUAL-TOOL"


def test_photos_page_batch_review_supports_per_photo_shot_types(
    qapp, usability_fake_config, usability_fake_project, frozen_project_date
):
    page = PhotosPage(usability_fake_config)
    page.show()

    click_button(page, "Refresh Incoming Photos")
    page.incoming_list.item(0).setSelected(True)
    page.incoming_list.item(1).setSelected(True)
    page.plant_edit.setText("Molding")
    page.press_edit.setText("Press 101")
    page.date_edit.setText("2026-05-19")
    page.audit_id_edit.setText("AUD-20260518-001")

    click_button(page, "Build Batch Review")
    first_view = page.batch_table.cellWidget(0, page.BATCH_VIEW_COL)
    second_view = page.batch_table.cellWidget(1, page.BATCH_VIEW_COL)
    first_view.setCurrentText("Overall EOAT")
    second_view.setCurrentText("Sensors")

    click_button(page, "Preview Rename/Move")
    preview_text = page.result_panel.viewer.toPlainText()

    assert "OverallEOAT" in preview_text
    assert "Sensors" in preview_text

    click_button(page, "Confirm Intake")
    wait_for_background_tasks()

    rows = row_dicts(
        usability_fake_project / "01_EOAT_Audit" / "EOAT_Audit_Database" / "EOAT_Master_Tracker.xlsx",
        "Photo Index",
    )
    related = [row for row in rows if row["Related Audit ID"] == "AUD-20260518-001"]
    assert any(row["EOAT Area Shown"] == "Overall EOAT" for row in related)
    assert any(row["EOAT Area Shown"] == "Sensors" for row in related)


def test_photos_page_batch_review_related_ids_are_dropdowns(
    qapp, usability_fake_config, usability_fake_project, frozen_project_date
):
    from PySide6.QtWidgets import QComboBox

    page = PhotosPage(usability_fake_config)
    page.show()

    click_button(page, "Refresh Incoming Photos")
    page.incoming_list.item(0).setSelected(True)
    page.plant_edit.setText("Molding")
    page.press_edit.setText("Press 101")
    page.date_edit.setText("2026-05-19")
    page.audit_id_edit.setText("AUD-20260518-001")
    page.issue_id_edit.setText("ISS-001")

    click_button(page, "Build Batch Review")
    audit_widget = page.batch_table.cellWidget(0, page.BATCH_AUDIT_COL)
    issue_widget = page.batch_table.cellWidget(0, page.BATCH_ISSUE_COL)

    assert isinstance(audit_widget, QComboBox)
    assert isinstance(issue_widget, QComboBox)
    assert "AUD-20260518-002" in _combo_data_values(audit_widget)
    assert "ISS-002" in _combo_data_values(issue_widget)

    audit_widget.setCurrentIndex(audit_widget.findData("AUD-20260518-002"))
    issue_widget.setCurrentIndex(issue_widget.findData("ISS-002"))

    _photos, metadata = page.selected_batch_metadata()
    assert metadata[0]["related_audit_id"] == "AUD-20260518-002"
    assert metadata[0]["related_issue_id"] == "ISS-002"
