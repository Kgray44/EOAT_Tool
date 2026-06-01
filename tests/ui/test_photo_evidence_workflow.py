from __future__ import annotations

import pytest
from openpyxl import load_workbook

from app.pages.photos import PhotosPage
from core.paths import resolve_project_paths
from core.photo_evidence import audit_photo_intake_folder
from core.workbook_schema import get_expected_headers
from tests.ui.helpers import click_button

pytestmark = pytest.mark.usability


def _append_inventory_row(project_root, values: dict[str, str]) -> None:
    workbook_path = resolve_project_paths(project_root).master_workbook
    workbook = load_workbook(workbook_path)
    ws = workbook["EOAT Inventory"]
    headers = [cell.value for cell in ws[1]]
    row = {header: "" for header in get_expected_headers("EOAT Inventory")}
    row.update(values)
    ws.append([row.get(header, "") for header in headers])
    workbook.save(workbook_path)
    workbook.close()


def test_photos_page_evidence_folder_checklist_and_open_actions(
    qapp, fake_config, fake_project, captured_open_requests
):
    _append_inventory_row(
        fake_project,
        {
            "Audit ID": "AUD-UI-EVID-001",
            "Audit Date": "2026-05-18",
            "Auditor": "Synthetic Auditor",
            "Plant/Area": "Plant 4",
            "Press/Machine #": "Press 12",
            "Robot Type": "Wittmann R9",
            "EOAT Type": "Vacuum",
            "Status": "Complete",
            "Sensors Present?": "No",
            "Quick Disconnects Present?": "No",
        },
    )
    page = PhotosPage(fake_config)
    page.show()
    page.audit_id_edit.setText("AUD-UI-EVID-001")

    click_button(page, "Refresh Evidence Coverage")
    assert page.evidence_table.rowCount() > 0
    assert "required missing" in page.result_panel.viewer.toPlainText()

    click_button(page, "Create Audit Intake Folder")
    folder = audit_photo_intake_folder(fake_project, "AUD-UI-EVID-001")
    assert folder.exists()

    click_button(page, "Export Photo Checklist")
    assert list(folder.glob("Photo_Checklist_AUD-UI-EVID-001_*.md"))

    click_button(page, "Open Audit Intake Folder")
    assert captured_open_requests[-1] == folder
