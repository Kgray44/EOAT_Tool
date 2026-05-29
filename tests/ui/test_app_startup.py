from __future__ import annotations

import pytest
from PySide6.QtWidgets import QLabel

from app.navigation import NAV_ITEMS
from core.constants import DEFAULT_PROJECT_ROOT
from tests.ui.helpers import wait_for_background_tasks, wait_until

pytestmark = pytest.mark.usability


def test_full_app_startup_uses_fake_project_and_resolves_day2(qapp, fake_config, fake_project, frozen_project_date, monkeypatch):
    import app.dashboard_ui as dashboard_ui

    monkeypatch.setattr(dashboard_ui, "load_config", lambda: fake_config)
    window = dashboard_ui.DashboardWindow()
    window.show()
    wait_for_background_tasks()

    assert window.windowTitle() == "EOAT Command Center"
    assert str(fake_project) in window.config.project_root
    assert window.config.project_root != str(DEFAULT_PROJECT_ROOT)
    assert window.nav.topLevelItemCount() > 0
    assert window.stack.currentWidget() is window.pages["home"]

    home = window.pages["home"]
    wait_until(lambda: bool(home.cards["Resolved Project Day"].value_label.text()), timeout_ms=2000, message="home dashboard resolved day")
    assert home.cards["Resolved Project Day"].value_label.text().startswith("Week 1 Day 2")
    assert str(fake_project) in home.project_root_label.text()


def test_navigation_loads_every_sidebar_page_with_primary_controls(qapp, fake_config, monkeypatch):
    import app.dashboard_ui as dashboard_ui

    monkeypatch.setattr(dashboard_ui, "load_config", lambda: fake_config)
    window = dashboard_ui.DashboardWindow()
    window.show()
    wait_for_background_tasks()

    loaded = []
    for item in NAV_ITEMS:
        nav_item = None
        for top in range(window.nav.topLevelItemCount()):
            header = window.nav.topLevelItem(top)
            for child in range(header.childCount()):
                candidate = header.child(child)
                if candidate.data(0, 0x0100) == item.page_key:
                    nav_item = candidate
                    break
            if nav_item is not None:
                break
        assert nav_item is not None, item.label
        window.nav.setCurrentItem(nav_item)
        qapp.processEvents()
        wait_for_background_tasks()
        page = window.pages[item.page_key]
        labels = [label.text() for label in page.findChildren(QLabel)]
        expected_heading = {
            "home": "EOAT Command Center",
            "photos": "EOAT Photo Intake",
            "issue_analysis": "Issue Analysis",
            "standards_docs": "Standards & Documentation",
            "bom_spares": "BOM & Spare Parts",
        }.get(item.page_key, item.label)
        assert any(expected_heading in label for label in labels), item.label
        loaded.append(item.page_key)

    assert set(loaded) == {item.page_key for item in NAV_ITEMS}
