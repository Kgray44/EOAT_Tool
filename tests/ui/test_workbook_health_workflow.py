from __future__ import annotations

import pytest

from app.pages.workbook_health import WorkbookHealthPage
from core.audit_by_press import AUDIT_BY_PRESS_SHEET, REFRESH_ACTION_NAME
from core.workbook_io import workbook_sheet_names
from tests.ui.helpers import click_button, wait_for_background_tasks

pytestmark = pytest.mark.usability


def test_workbook_validation_generates_report_updates_cards_and_stubs_open(qapp, fake_config, fake_project, captured_open_requests):
    page = WorkbookHealthPage(fake_config)
    page.show()

    click_button(page, "Run Foundation Validation")
    wait_for_background_tasks()

    assert page.cards["Workbook Status"].value_label.text() in {"OK", "Needs attention"}
    assert page.cards["Missing Major Headers"].value_label.text() == "0"
    assert page.cards["Duplicate Audit IDs"].value_label.text() == "0"
    assert page.cards["Semantic Warnings"].value_label.text() == "0"
    assert page.findings_table.rowCount() >= 1
    assert list((fake_project / "00_Project_Admin" / "Validation_Reports").glob("Foundation_Validation_*.md"))
    assert list((fake_project / "00_Project_Admin" / "Validation_Reports").glob("Foundation_Validation_*.json"))

    click_button(page, "Open Validation Reports Folder")
    assert captured_open_requests[-1] == fake_project / "00_Project_Admin" / "Validation_Reports"


def test_workbook_health_refreshes_audit_by_press_view(qapp, fake_config, fake_project):
    page = WorkbookHealthPage(fake_config)
    page.show()

    assert AUDIT_BY_PRESS_SHEET not in workbook_sheet_names(fake_project / "01_EOAT_Audit" / "EOAT_Audit_Database" / "EOAT_Master_Tracker.xlsx")
    click_button(page, REFRESH_ACTION_NAME)
    wait_for_background_tasks()

    assert AUDIT_BY_PRESS_SHEET in workbook_sheet_names(fake_project / "01_EOAT_Audit" / "EOAT_Audit_Database" / "EOAT_Master_Tracker.xlsx")
