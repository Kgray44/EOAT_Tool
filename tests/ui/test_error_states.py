from __future__ import annotations

import json

import pytest
from openpyxl import load_workbook

from app.pages.audit_progress import AuditProgressPage
from app.pages.photos import PhotosPage
from app.pages.schedule import SchedulePage
from app.pages.workbook_health import WorkbookHealthPage
from core.config import UserConfig
from tests.fixtures.fake_project import create_fake_eoat_project
from tests.ui.helpers import click_button, wait_for_background_tasks


pytestmark = pytest.mark.usability


def test_missing_master_workbook_error_is_friendly(qapp, minimal_fake_project):
    config = UserConfig(project_root=str(minimal_fake_project), project_start_date="2026-05-18")
    page = WorkbookHealthPage(config)
    page.show()

    click_button(page, "Run Foundation Validation")
    wait_for_background_tasks()
    text = page.result_panel.viewer.toPlainText()
    assert "FAILED" in text or "Needs attention" in text
    assert "Master workbook" in text or "workbook" in text.lower()


def test_missing_schedule_file_empty_state_does_not_crash(qapp, minimal_fake_project):
    config = UserConfig(project_root=str(minimal_fake_project), project_start_date="2026-05-18")
    page = SchedulePage(config)
    page.show()

    assert page.task_table.rowCount() == 0
    assert "No schedule/task progress week files found" in page.summary_label.text()
    assert "Project start date" not in page.resolved_label.text() or "Resolved:" in page.resolved_label.text()


def test_missing_project_start_date_fallback_is_visible(qapp, fake_project):
    config = UserConfig(project_root=str(fake_project), project_start_date="")
    page = SchedulePage(config)
    page.show()

    assert "Week 1 Day 1" in page.resolved_label.text()
    assert "Project start date" in page.resolved_label.text() or "inferred" in page.resolved_label.text()


def test_corrupted_task_progress_json_shows_empty_progress_not_traceback(qapp, fake_project):
    progress = fake_project / "00_Project_Admin" / "task_progress_week1.json"
    progress.write_text("{this is not valid json", encoding="utf-8")
    config = UserConfig(project_root=str(fake_project), project_start_date="2026-05-18")

    page = SchedulePage(config)
    page.show()

    assert page.task_table.rowCount() == 0
    assert "Traceback" not in page.summary_label.text()


def test_workbook_missing_required_sheet_reports_error_without_crash(qapp, tmp_path):
    project = create_fake_eoat_project(tmp_path)
    workbook_path = project / "01_EOAT_Audit" / "EOAT_Audit_Database" / "EOAT_Master_Tracker.xlsx"
    wb = load_workbook(workbook_path)
    del wb["Issue Log"]
    wb.save(workbook_path)
    wb.close()
    config = UserConfig(project_root=str(project), project_start_date="2026-05-18")

    page = WorkbookHealthPage(config)
    page.show()
    click_button(page, "Run Foundation Validation")
    wait_for_background_tasks()

    text = page.result_panel.viewer.toPlainText()
    assert "Issue Log" in text
    assert "Traceback" not in text


def test_tool_exception_is_captured_as_user_visible_failure(qapp, fake_config, monkeypatch):
    import app.pages.workbook_health as workbook_health

    def boom(_project_root):
        raise RuntimeError("synthetic tool failure")

    monkeypatch.setattr(workbook_health, "run_foundation_validation", boom)
    page = WorkbookHealthPage(fake_config)
    page.show()
    click_button(page, "Run Foundation Validation")
    wait_for_background_tasks()

    text = page.result_panel.viewer.toPlainText()
    assert "FAILED" in text
    assert "synthetic tool failure" in text


def test_empty_incoming_photos_error_path_is_friendly(qapp, fake_project):
    incoming = fake_project / "01_EOAT_Audit" / "Cell_Photos" / "Incoming_Photos"
    for path in incoming.iterdir():
        path.unlink()
    config = UserConfig(project_root=str(fake_project), project_start_date="2026-05-18")
    page = PhotosPage(config)
    page.show()

    click_button(page, "Confirm Intake")
    wait_for_background_tasks()
    text = page.result_panel.viewer.toPlainText()
    assert "No photos selected" in text
    assert "Traceback" not in text
