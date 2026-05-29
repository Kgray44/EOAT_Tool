from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.pages.settings import SettingsPage
from tests.ui.helpers import click_button, wait_for_background_tasks


pytestmark = pytest.mark.usability


def test_settings_save_reload_theme_audit_backups_and_open_stub(qapp, fake_config, fake_project, captured_open_requests, monkeypatch, tmp_path):
    import app.pages.settings as settings_module

    saved_path = tmp_path / "fake_config.json"
    saved = {"config": fake_config}

    def fake_save(config):
        saved["config"] = type(fake_config)(**config.to_dict())
        saved_path.write_text(json.dumps(config.to_dict(), indent=2), encoding="utf-8")
        return saved_path

    def fake_load():
        return saved["config"]

    monkeypatch.setattr(settings_module, "save_config", fake_save)
    monkeypatch.setattr(settings_module, "load_config", fake_load)

    page = SettingsPage(fake_config)
    page.show()

    assert page.project_root_edit.text() == str(fake_project)
    assert page.settings_tabs.count() >= 7
    assert page.has_unsaved_changes() is False
    page.settings_search_edit.setText("backup")
    assert page.settings_tabs.tabText(page.settings_tabs.currentIndex()) == "Backups & Safety"
    page.daily_report_time_edit.setText("18:30")
    assert page.has_unsaved_changes() is True
    page.theme_combo.setCurrentIndex(page.theme_combo.findData("dark"))
    click_button(page, "Save Settings")
    assert saved["config"].theme == "dark"
    assert saved["config"].scheduled_reports["daily_time"] == "18:30"
    assert page.has_unsaved_changes() is False

    page.theme_combo.setCurrentIndex(page.theme_combo.findData("light"))
    click_button(page, "Reload Settings")
    assert page.theme_combo.currentData() == "dark"
    assert page.daily_report_time_edit.text() == "18:30"

    click_button(page, "Run Full System Audit")
    wait_for_background_tasks()
    assert "System Audit" in page.status_label.text()

    click_button(page, "Backup Workbook")
    wait_for_background_tasks()
    click_button(page, "Create Light Project Backup")
    wait_for_background_tasks()
    backups = fake_project / "00_Project_Admin" / "Backups"
    assert list(backups.rglob("*"))

    click_button(page, "Open Backups Folder")
    assert captured_open_requests[-1] == backups


def test_settings_revert_restores_baseline(qapp, fake_config):
    page = SettingsPage(fake_config)
    page.show()
    original_time = page.daily_report_time_edit.text()

    page.daily_report_time_edit.setText("06:45")
    assert page.has_unsaved_changes() is True
    click_button(page, "Show Changes")
    assert "scheduled_reports" in page.status_label.text()

    click_button(page, "Revert Changes")

    assert page.daily_report_time_edit.text() == original_time
    assert page.has_unsaved_changes() is False


def test_settings_audit_default_manager_actions(qapp, fake_config):
    page = SettingsPage(fake_config)
    page.show()
    table = page.audit_default_rules_table
    starting_rows = table.rowCount()

    table.selectRow(0)
    click_button(page, "Duplicate")
    assert table.rowCount() == starting_rows + 1
    assert page.has_unsaved_changes() is True

    table.selectRow(table.rowCount() - 1)
    click_button(page, "Disable")
    assert table.item(table.currentRow(), 1).text() == "No"

    click_button(page, "Preview Applied Defaults")
    assert "Preview Applied Defaults" in page.status_label.text()
