from __future__ import annotations

import pytest
from PySide6.QtWidgets import QComboBox, QPushButton, QTableWidget

from app.navigation import NAV_ITEMS
from tests.ui.helpers import wait_for_background_tasks


pytestmark = pytest.mark.usability


def test_theme_switching_persists_and_pages_survive_dark_and_light(qapp, fake_config, monkeypatch):
    import app.dashboard_ui as dashboard_ui

    saved = {}

    def fake_save_config(config):
        saved.update(config.to_dict())
        return "fake-test-config.json"

    monkeypatch.setattr(dashboard_ui, "load_config", lambda: fake_config)
    import app.pages.settings as settings_module

    monkeypatch.setattr(settings_module, "save_config", fake_save_config)
    window = dashboard_ui.DashboardWindow()
    window.show()
    wait_for_background_tasks()

    window._show_page("settings")
    settings = window.pages["settings"]
    combo = settings.theme_combo
    assert isinstance(combo, QComboBox)
    combo.setCurrentIndex(combo.findData("dark"))
    settings.save()
    qapp.processEvents()

    assert window.config.theme == "dark"
    assert saved["theme"] == "dark"
    assert "QPushButton" in qapp.styleSheet()
    assert "QTableWidget" in qapp.styleSheet()

    for item in NAV_ITEMS:
        window._show_page(item.page_key)
        qapp.processEvents()
        page = window.pages[item.page_key]
        assert page.findChildren(QPushButton) or page.findChildren(QTableWidget) or item.page_key == "tool_registry"

    window._show_page("settings")
    combo.setCurrentIndex(combo.findData("light"))
    settings.save()
    assert window.config.theme == "light"
    assert saved["theme"] == "light"
