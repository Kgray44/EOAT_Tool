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
