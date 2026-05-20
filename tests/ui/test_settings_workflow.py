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
    page.theme_combo.setCurrentIndex(page.theme_combo.findData("dark"))
    click_button(page, "Save Settings")
    assert saved["config"].theme == "dark"

    page.theme_combo.setCurrentIndex(page.theme_combo.findData("light"))
    click_button(page, "Reload Settings")
    assert page.theme_combo.currentData() == "dark"

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
