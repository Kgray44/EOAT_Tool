from __future__ import annotations

import os
import json

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton

from app.dashboard_ui import DashboardWindow
from app.navigation import NAV_ITEMS, NAV_SECTIONS
from app.pages.home import HomePage
from app.pages.schedule import SchedulePage
from app.pages.settings import SettingsPage
from app.ui_constants import DEFAULT_WINDOW_HEIGHT, DEFAULT_WINDOW_WIDTH, SIDEBAR_WIDTH
from app.widgets.workflow_card import WorkflowCard
from core.config import UserConfig


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_main_window_smoke_short_default_size(fake_config):
    _app()
    window = DashboardWindow(fake_config)

    assert window.windowTitle() == "EOAT Command Center"
    assert window.width() == DEFAULT_WINDOW_WIDTH
    assert window.height() == DEFAULT_WINDOW_HEIGHT
    assert window.nav.minimumWidth() >= SIDEBAR_WIDTH


def test_main_window_smoke_dark_mode(fake_config):
    app = _app()
    app.setStyleSheet("")
    window = DashboardWindow(fake_config)
    window.apply_theme("dark")

    assert window.config.theme == "dark"
    assert "QTableWidget" in app.styleSheet()


def test_grouped_navigation_pages_can_be_created(fake_config, monkeypatch):
    _app()
    original_hook = DashboardWindow._call_optional_page_hook

    def skip_show_hooks(page, hook_name: str, *args):
        if hook_name == "on_show":
            return True
        return original_hook(page, hook_name, *args)

    monkeypatch.setattr(DashboardWindow, "_call_optional_page_hook", staticmethod(skip_show_hooks))
    window = DashboardWindow(fake_config)

    section_names = [section.label for section in NAV_SECTIONS]
    assert section_names == ["Overview", "Capture", "Analysis", "Standards", "Output", "System"]

    for item in NAV_ITEMS:
        window._show_page(item.page_key)
        assert item.page_key in window.pages


def test_home_page_contains_workflow_cards_and_key_actions():
    _app()
    page = HomePage(UserConfig())
    cards = page.findChildren(WorkflowCard)
    buttons = {button.text() for button in page.findChildren(QPushButton)}

    assert len(cards) >= 5
    for label in [
        "Generate Morning Plan",
        "Add Audit Entry",
        "Intake Photos",
        "Validate Project Foundation",
        "Run Issue Analysis",
        "Generate Weekly Summary",
        "Build Final Handoff Package",
    ]:
        assert label in buttons


def test_schedule_page_displays_resolved_day_and_morning_button(fake_project):
    _app()
    admin = fake_project / "00_Project_Admin"
    (admin / "project_schedule_week1.json").write_text(json.dumps({"days": {"1": ["Task A"], "2": ["Task B"]}}), encoding="utf-8")
    (admin / "task_progress_week1.json").write_text(
        json.dumps({"tasks": [{"task_id": "W1D2T1", "day": "2", "task_text": "Task B", "status": "Not started"}]}),
        encoding="utf-8",
    )
    page = SchedulePage(UserConfig(project_root=str(fake_project), project_start_date="2026-05-18"))

    assert "Resolved: Week" in page.resolved_label.text()
    assert page.morning_button.text().startswith("Generate Morning Plan for Week")
    page.override_checkbox.setChecked(True)
    assert "(manual override)" in page.morning_button.text()


def test_settings_page_smoke_handlers_exist():
    _app()
    page = SettingsPage(UserConfig())

    assert page.project_root_edit.text()
    assert page.git_edit is not None
    assert page.theme_combo.findData("dark") >= 0
    for handler in ["save", "reload", "test_git", "run_system_audit", "backup_workbook", "backup_light"]:
        assert callable(getattr(page, handler))
