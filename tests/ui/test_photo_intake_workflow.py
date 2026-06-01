from __future__ import annotations

import json

import pytest

from app.pages.photos import PhotosPage
from core.workbook_io import row_dicts
from tests.ui.helpers import click_button, wait_for_background_tasks

pytestmark = pytest.mark.usability


def test_photo_intake_previews_copies_and_indexes_selected_images(qapp, fake_config, fake_project, frozen_project_date):
    page = PhotosPage(fake_config)
    page.show()

    click_button(page, "Refresh Incoming Photos")
    assert page.incoming_list.count() >= 2
    page.incoming_list.item(0).setSelected(True)
    page.incoming_list.item(1).setSelected(True)
    page.plant_edit.setText("Molding")
    page.press_edit.setText("Press 101")
    page.date_edit.setText("2026-05-19")
    page.view_combo.setCurrentText("Vacuum Cups / Grippers")
    page.audit_id_edit.setText("AUD-20260518-001")
    page.description_edit.setPlainText("Fake intake usability photos.")
    page.notes_edit.setPlainText("No real internship image files used.")

    click_button(page, "Preview Rename/Move")
    preview_text = page.result_panel.viewer.toPlainText()
    assert "Molding_Press101_EOAT_2026-05-19_VacuumCupsGrippers" in preview_text

    click_button(page, "Confirm Intake")
    wait_for_background_tasks()

    target_dir = fake_project / "01_EOAT_Audit" / "Cell_Photos" / "Vacuum_Cups_Grippers"
    copied = list(target_dir.glob("Molding_Press101_EOAT_2026-05-19_VacuumCupsGrippers_*"))
    assert len(copied) == 2
    rows = row_dicts(fake_project / "01_EOAT_Audit" / "EOAT_Audit_Database" / "EOAT_Master_Tracker.xlsx", "Photo Index")
    assert sum(1 for row in rows if row["Related Audit ID"] == "AUD-20260518-001") >= 2

    activity_log = fake_project / "00_Project_Admin" / "Activity_Logs" / "activity_log.jsonl"
    entries = [json.loads(line) for line in activity_log.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert any(entry["tool_id"] == "photo_intake" and entry["success"] for entry in entries)


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
    assert "Tool #: TOOL-B" in page.audit_context_label.text()
    assert "Gripper Size" not in page.audit_context_label.text()

    click_button(page, "Use Next Missing Shot Type")

    assert page.view_combo.currentText() in {"Overall EOAT", "Tool Connection", "Grippers", "Tool Label / ID Plate"}


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
