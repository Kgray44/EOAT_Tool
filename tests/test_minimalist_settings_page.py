from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QCheckBox, QComboBox, QLabel, QPushButton

from app.atlas.minimalist import settings_page as settings_page_module
from app.atlas.minimalist.fit_check import fit_check_styles
from app.atlas.minimalist.library import ENTITY_TOOL, LibraryBrowseStateView, MinimalistLibraryContent
from app.atlas.minimalist.library import library_widget_styles
from app.atlas.minimalist.settings_page import DialogAction, MinimalistSettingsContent, SettingsConfirmationDialog
from app.atlas.minimalist.settings_store import get_default_settings, get_effective_default_settings, load_settings, reset_section, save_settings
from app.atlas.minimalist.theme import (
    REQUIRED_THEME_TOKENS,
    THEME_TOKENS,
    effective_minimalist_theme,
    minimalist_tokens,
    normalize_theme_preference,
    settings_page_styles,
)
from core.config import UserConfig


def test_minimalist_theme_tokens_cover_dark_light_and_system() -> None:
    assert {"dark", "light"}.issubset(THEME_TOKENS)
    for theme in ("dark", "light"):
        tokens = minimalist_tokens(theme).as_dict()
        for key in REQUIRED_THEME_TOKENS:
            assert tokens[key]

    assert normalize_theme_preference("mystery") == "dark"
    assert normalize_theme_preference("SYSTEM") == "system"
    assert effective_minimalist_theme("system") in {"dark", "light"}
    assert "QPushButton#SettingsPrimaryButton" in settings_page_styles("light")
    assert "QCheckBox#SettingsCheckBox::indicator:checked:disabled" in settings_page_styles("light")
    assert "QPushButton#SettingsSegmentButton:checked:disabled" in settings_page_styles("light")
    assert "#0c1b2e" in fit_check_styles("light")
    assert "#0c1b2e" in library_widget_styles("light")


def test_minimalist_settings_store_merges_defaults_without_dropping_user_values(tmp_path: Path) -> None:
    settings_path = tmp_path / "eoat_atlas_settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "app": {"theme": "light"},
                "paths": {"eoat_master_tracker": "C:/EOAT/Data/EOAT_Master_Tracker.xlsx"},
                "custom_future_section": {"keep": True},
            }
        ),
        encoding="utf-8",
    )

    loaded = load_settings(settings_path)

    assert loaded["app"]["theme"] == "light"
    assert loaded["paths"]["eoat_master_tracker"] == "C:/EOAT/Data/EOAT_Master_Tracker.xlsx"
    assert loaded["data_loading"]["refresh_on_launch"] is True
    assert loaded["fit_check"]["compatibility_strictness"] == "strict"
    assert loaded["custom_future_section"] == {"keep": True}


def test_reset_section_only_resets_selected_category(tmp_path: Path) -> None:
    settings_path = tmp_path / "settings.json"
    settings = load_settings(settings_path)
    settings["fit_check"]["compatibility_strictness"] = "loose"
    settings["library"]["cards_per_page"] = 48
    save_settings(settings, settings_path)

    reset = reset_section(load_settings(settings_path), "fit_check")

    assert reset["fit_check"]["compatibility_strictness"] == "strict"
    assert reset["library"]["cards_per_page"] == 48


def test_minimalist_settings_page_switches_category_without_duplicate_nav(qapp, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("EOAT_ATLAS_USER_DATA_DIR", str(tmp_path / "user_data"))
    controller = SimpleNamespace(config=UserConfig(project_root=str(tmp_path)), minimalist_app_settings={})
    content = MinimalistSettingsContent(controller)
    content.resize(1400, 900)
    content.show()
    qapp.processEvents()

    assert content.selected_key == "data_sources"
    data_sources_text = _widget_text(content.main_panel)
    assert "Workbook Sources" in data_sources_text
    assert "Refresh Behavior" not in data_sources_text

    content.select_section("fit_check")
    qapp.processEvents()
    assert content.selected_key == "fit_check"
    assert "Compatibility Strictness" in _widget_text(content.main_panel)

    content.select_section("library")
    qapp.processEvents()
    library_text = _widget_text(content.main_panel)

    assert "Default Library tab" in library_text
    assert "Cards per page" in library_text
    assert "EOAT default sort" in library_text
    assert "Workbook Sources" not in library_text
    assert "Reference Links" not in library_text

    assert not content.save_button.isEnabled()
    content._start_admin_session()
    content._set_setting("library.cards_per_page", 48)
    assert content.save_button.isEnabled()
    assert content.unsaved_label.isVisible()

    content.save_current_settings()

    assert not content.save_button.isEnabled()
    assert load_settings(content.settings_file)["library"]["cards_per_page"] == 48
    content.close()


def test_dynamic_source_rows_are_unregistered_before_deferred_delete(qapp, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("EOAT_ATLAS_USER_DATA_DIR", str(tmp_path / "user_data"))
    controller = SimpleNamespace(config=UserConfig(project_root=str(tmp_path)), minimalist_app_settings={})
    content = MinimalistSettingsContent(controller)
    old_rows = tuple(content.source_rows.values())

    content.select_section("refresh_cache")
    assert content.source_rows == {}
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()

    content._refresh_dynamic_rows()
    assert content.source_rows == {}
    assert all(row._disposing for row in old_rows)
    content.close()


def test_settings_reconstruction_and_bundle_changes_leave_only_live_rows(qapp, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("EOAT_ATLAS_USER_DATA_DIR", str(tmp_path / "user_data"))
    controller = SimpleNamespace(config=UserConfig(project_root=str(tmp_path)), minimalist_app_settings={})
    content = MinimalistSettingsContent(controller)
    bundles = (SimpleNamespace(loaded_at="2026-07-13 12:00"), None)

    for index in range(12):
        content.select_section("refresh_cache")
        content.set_bundle(bundles[index % 2])
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        qapp.processEvents()
        assert content.source_rows == {}
        content.select_section("data_sources")
        content.set_bundle(bundles[(index + 1) % 2])
        qapp.processEvents()
        assert len(content.source_rows) == len(settings_page_module.SOURCE_SPECS)
        assert all(row.is_live() for row in content.source_rows.values())

    content.close()


def test_programmatic_checkbox_sync_is_not_a_user_edit(qapp, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("EOAT_ATLAS_USER_DATA_DIR", str(tmp_path / "user_data"))
    controller = SimpleNamespace(config=UserConfig(project_root=str(tmp_path)), minimalist_app_settings={})
    content = MinimalistSettingsContent(controller)
    content.resize(1400, 900)
    content.show()
    content._start_admin_session()
    content.select_section("refresh_cache")
    qapp.processEvents()
    checkbox = _setting_checkbox(content, "data_loading.refresh_on_launch")
    calls: list[tuple[str, object]] = []
    original_handler = content._on_setting_changed

    def counting_handler(path, value, **kwargs):
        calls.append((path, value))
        return original_handler(path, value, **kwargs)

    monkeypatch.setattr(content, "_on_setting_changed", counting_handler)
    with content._settings_ui_sync():
        checkbox.setChecked(not checkbox.isChecked())

    assert calls == []
    assert not content.dirty_keys
    content._sync_visible_controls_from_draft()
    assert checkbox.isChecked() == bool(content._setting("data_loading.refresh_on_launch"))
    assert calls == []
    content.close()


def test_user_checkbox_toggle_runs_once_and_survives_admin_rebuilds(qapp, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("EOAT_ATLAS_USER_DATA_DIR", str(tmp_path / "user_data"))
    controller = SimpleNamespace(config=UserConfig(project_root=str(tmp_path)), minimalist_app_settings={})
    content = MinimalistSettingsContent(controller)
    content.resize(1400, 900)
    content.show()
    content._start_admin_session()
    content.select_section("refresh_cache")
    qapp.processEvents()
    checkbox = _setting_checkbox(content, "data_loading.refresh_on_launch")
    calls: list[tuple[str, object]] = []
    original_handler = content._on_setting_changed

    def counting_handler(path, value, **kwargs):
        calls.append((path, value))
        return original_handler(path, value, **kwargs)

    monkeypatch.setattr(content, "_on_setting_changed", counting_handler)
    expected = not checkbox.isChecked()
    QTest.mouseClick(checkbox, Qt.MouseButton.LeftButton)

    assert calls == [("data_loading.refresh_on_launch", expected)]
    assert content._setting("data_loading.refresh_on_launch") is expected
    assert "data_loading.refresh_on_launch" in content.dirty_keys

    for _ in range(6):
        content._sync_admin_state(rerender=True)
        qapp.processEvents()
        rebuilt = _setting_checkbox(content, "data_loading.refresh_on_launch")
        assert rebuilt.isChecked() is expected
        assert rebuilt.isEnabled()
    content.close()


def test_minimalist_settings_dirty_indicators_follow_section_state(qapp, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("EOAT_ATLAS_USER_DATA_DIR", str(tmp_path / "user_data"))
    controller = SimpleNamespace(config=UserConfig(project_root=str(tmp_path)), minimalist_app_settings={})
    content = MinimalistSettingsContent(controller)
    content.resize(1400, 900)
    content.show()
    qapp.processEvents()

    content.select_section("refresh_cache")
    content._start_admin_session()
    content._set_setting("data_loading.refresh_on_launch", False)
    qapp.processEvents()

    assert content.save_button.isEnabled()
    assert content.unsaved_label.isVisible()
    assert "data_loading.refresh_on_launch" in content.dirty_keys
    assert "refresh_cache" in content.dirty_sections
    assert content.setting_rows["data_loading.refresh_on_launch"][0].dirty_indicator.isVisible()
    assert content.sidebar_items["refresh_cache"].dirty_indicator.isVisible()
    assert content.panel_header.dirty_pill.isVisible()

    content.select_section("library")
    qapp.processEvents()

    assert content.sidebar_items["refresh_cache"].dirty_indicator.isVisible()
    assert not content.panel_header.dirty_pill.isVisible()

    content._set_setting("library.cards_per_page", 48)
    assert {"refresh_cache", "library"}.issubset(content.dirty_sections)
    assert content.sidebar_items["library"].dirty_indicator.isVisible()
    assert content.panel_header.dirty_pill.isVisible()

    content._set_setting("library.cards_per_page", content.saved_settings["library"]["cards_per_page"])
    assert "library.cards_per_page" not in content.dirty_keys
    assert "library" not in content.dirty_sections
    assert "refresh_cache" in content.dirty_sections

    content.save_current_settings()

    assert not content.save_button.isEnabled()
    assert not content.unsaved_label.isVisible()
    assert not any(item.dirty_indicator.isVisible() for item in content.sidebar_items.values())
    content.close()


def test_settings_page_restores_full_registry_and_has_no_one_option_dropdowns(qapp, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("EOAT_ATLAS_USER_DATA_DIR", str(tmp_path / "user_data"))
    controller = SimpleNamespace(config=UserConfig(project_root=str(tmp_path)), minimalist_app_settings={})
    content = MinimalistSettingsContent(controller)
    content.show()
    qapp.processEvents()

    sidebar_titles = _widget_text(content.sidebar)
    for title in (
        "Data Sources",
        "Refresh & Cache",
        "Write Safety",
        "Search & Navigation",
        "Fit Check",
        "Library",
        "Display & Accessibility",
        "Setup Packet / PDF",
        "Validation & Data Health",
        "Reference Documents",
        "Diagnostics & Support",
        "About",
    ):
        assert title in sidebar_titles

    assert all(item["implemented"] for item in settings_page_module.VISIBLE_SETTINGS_AUDIT)
    for item in settings_page_module.SETTINGS_REGISTRY:
        if item.visible and item.control in {"segmented", "combo", "dropdown"}:
            assert len(item.options) >= 2

    content.select_section("library")
    qapp.processEvents()
    assert "EOAT default sort" in _widget_text(content.main_panel)
    for combo in content.main_panel.findChildren(QComboBox):
        assert combo.count() != 1
    content.close()


def test_settings_are_locked_until_admin_is_active(qapp, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("EOAT_ATLAS_USER_DATA_DIR", str(tmp_path / "user_data"))
    controller = SimpleNamespace(config=UserConfig(project_root=str(tmp_path)), minimalist_app_settings={})
    content = MinimalistSettingsContent(controller)
    content.show()
    qapp.processEvents()
    content.select_section("refresh_cache")
    original = content.draft_settings["data_loading"]["refresh_on_launch"]

    assert not content.admin_active
    assert "Settings Locked" in content.admin_status_label.text()
    content._set_setting("data_loading.refresh_on_launch", not original)

    assert content.draft_settings["data_loading"]["refresh_on_launch"] is original
    assert not content.save_button.isEnabled()
    assert not content.dirty_keys

    content._start_admin_session()
    content._set_setting("data_loading.refresh_on_launch", not original)
    qapp.processEvents()

    assert content.draft_settings["data_loading"]["refresh_on_launch"] is (not original)
    assert content.save_button.isEnabled()
    assert content.setting_rows["data_loading.refresh_on_launch"][0].dirty_indicator.isVisible()
    content.close()


def test_admin_logout_timeout_values_are_validated(tmp_path: Path, caplog) -> None:
    settings_path = tmp_path / "settings.json"
    allowed_values = (0, 15, 30, 60, 120, 300)

    for value in allowed_values:
        payload = get_default_settings()
        payload["admin"]["logout_after_leaving_settings_seconds"] = value
        save_settings(payload, settings_path)
        assert load_settings(settings_path)["admin"]["logout_after_leaving_settings_seconds"] == value

    settings_path.write_text(
        json.dumps({"admin": {"logout_after_leaving_settings_seconds": 75}}),
        encoding="utf-8",
    )

    loaded = load_settings(settings_path)

    assert loaded["admin"]["logout_after_leaving_settings_seconds"] == 60
    assert "Invalid admin auto-logout timeout" in caplog.text


def test_admin_logout_timeout_control_requires_admin_and_marks_diagnostics_dirty(qapp, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("EOAT_ATLAS_USER_DATA_DIR", str(tmp_path / "user_data"))
    controller = SimpleNamespace(config=UserConfig(project_root=str(tmp_path)), minimalist_app_settings={})
    content = MinimalistSettingsContent(controller)
    content.resize(1400, 900)
    content.show()
    content.select_section("diagnostics_support")
    qapp.processEvents()

    combo = _setting_combo(content, "admin.logout_after_leaving_settings_seconds")

    assert [combo.itemText(index) for index in range(combo.count())] == [
        "Immediately",
        "15 sec",
        "30 sec",
        "1 min",
        "2 min",
        "5 min",
    ]
    assert [combo.itemData(index) for index in range(combo.count())] == [0, 15, 30, 60, 120, 300]
    assert combo.currentText() == "1 min"
    assert not combo.isEnabled()
    assert combo.toolTip() == "Admin access required to change auto-logout timing."

    content._start_admin_session()
    combo = _setting_combo(content, "admin.logout_after_leaving_settings_seconds")
    combo.setCurrentIndex(combo.findData(15))
    qapp.processEvents()

    assert combo.isEnabled()
    assert content.draft_settings["admin"]["logout_after_leaving_settings_seconds"] == 15
    assert "admin.logout_after_leaving_settings_seconds" in content.dirty_keys
    assert "diagnostics_support" in content.dirty_sections
    assert content.setting_rows["admin.logout_after_leaving_settings_seconds"][0].dirty_indicator.isVisible()
    assert content.sidebar_items["diagnostics_support"].dirty_indicator.isVisible()
    assert content.save_button.isEnabled()

    assert content.save_current_settings()
    assert load_settings(content.settings_file)["admin"]["logout_after_leaving_settings_seconds"] == 15
    content.close()


def test_admin_logout_timer_uses_saved_timeout_and_cancels_on_return(qapp, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("EOAT_ATLAS_USER_DATA_DIR", str(tmp_path / "user_data"))
    notices: list[str] = []
    controller = SimpleNamespace(
        config=UserConfig(project_root=str(tmp_path)),
        minimalist_app_settings={},
        show_status=lambda message: notices.append(message),
    )
    content = MinimalistSettingsContent(controller)
    content.saved_settings["admin"]["logout_after_leaving_settings_seconds"] = 15
    content.draft_settings = deepcopy(content.saved_settings)
    content._start_admin_session()

    timer = content._admin_logout_timer
    content.page_hidden()

    assert content.admin_active
    assert timer.isActive()
    assert timer.interval() == 15_000

    content.page_hidden()
    assert content._admin_logout_timer is timer
    assert timer.isActive()
    assert timer.interval() == 15_000

    content.page_shown()
    assert not timer.isActive()
    assert content.admin_active

    content.saved_settings["admin"]["logout_after_leaving_settings_seconds"] = 0
    content.draft_settings = deepcopy(content.saved_settings)
    content.page_hidden()

    assert not content.admin_active
    assert not timer.isActive()
    assert notices[-1] == "Admin session ended."
    content.close()


def test_admin_timeout_discards_unsaved_settings_safely(qapp, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("EOAT_ATLAS_USER_DATA_DIR", str(tmp_path / "user_data"))
    controller = SimpleNamespace(config=UserConfig(project_root=str(tmp_path)), minimalist_app_settings={})
    content = MinimalistSettingsContent(controller)
    content._start_admin_session()
    content._set_setting("library.cards_per_page", 48)

    assert content.dirty_keys
    content._admin_timeout_elapsed()

    assert not content.admin_active
    assert not content.dirty_keys
    assert content.draft_settings == content.saved_settings
    assert content._pending_admin_timeout_notice == "Admin session ended. Unsaved settings were discarded."
    content.close()


def test_library_settings_are_consumed_by_library_browse_view(qapp, tmp_path: Path) -> None:
    controller = SimpleNamespace(
        config=UserConfig(project_root=str(tmp_path)),
        minimalist_app_settings={"library": {"default_tab": "tools", "cards_per_page": 12}},
    )
    content = MinimalistLibraryContent(controller)
    content.resize(1400, 900)
    content.show()
    qapp.processEvents()

    assert content.scope_type == ENTITY_TOOL
    assert isinstance(content.current_view, LibraryBrowseStateView)
    assert content.current_view._configured_grid_page_size == 12
    content.close()


def test_reset_section_uses_working_settings_until_save(qapp, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("EOAT_ATLAS_USER_DATA_DIR", str(tmp_path / "user_data"))
    controller = SimpleNamespace(config=UserConfig(project_root=str(tmp_path)), minimalist_app_settings={})
    content = MinimalistSettingsContent(controller)
    content.select_section("refresh_cache")
    content._start_admin_session()
    content._set_setting("data_loading.refresh_on_launch", False)
    assert content.save_current_settings()
    assert load_settings(content.settings_file)["data_loading"]["refresh_on_launch"] is False

    monkeypatch.setattr(settings_page_module, "show_settings_confirmation", lambda *args, **kwargs: "reset")
    content.reset_current_section()
    qapp.processEvents()

    assert content.draft_settings["data_loading"]["refresh_on_launch"] is True
    assert load_settings(content.settings_file)["data_loading"]["refresh_on_launch"] is False
    assert content.save_button.isEnabled()
    assert content.dirty_sections == {"refresh_cache"}

    assert content.save_current_settings()
    assert load_settings(content.settings_file)["data_loading"]["refresh_on_launch"] is True
    content.close()


def test_reset_all_settings_requires_save_before_persisting(qapp, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("EOAT_ATLAS_USER_DATA_DIR", str(tmp_path / "user_data"))
    controller = SimpleNamespace(config=UserConfig(project_root=str(tmp_path)), minimalist_app_settings={})
    content = MinimalistSettingsContent(controller)
    content._start_admin_session()
    content._set_setting("library.cards_per_page", 48)
    assert content.save_current_settings()
    assert load_settings(content.settings_file)["library"]["cards_per_page"] == 48

    monkeypatch.setattr(settings_page_module, "show_settings_confirmation", lambda *args, **kwargs: "reset")
    content.reset_all_settings()
    qapp.processEvents()

    assert content.draft_settings["library"]["cards_per_page"] == get_default_settings()["library"]["cards_per_page"]
    assert load_settings(content.settings_file)["library"]["cards_per_page"] == 48
    assert content.save_button.isEnabled()
    assert "library" in content.dirty_sections

    assert content.save_current_settings()
    assert load_settings(content.settings_file)["library"]["cards_per_page"] == 24
    content.close()


def test_validation_action_does_not_create_unsaved_settings(qapp, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("EOAT_ATLAS_USER_DATA_DIR", str(tmp_path / "user_data"))
    controller = SimpleNamespace(config=UserConfig(project_root=str(tmp_path)), minimalist_app_settings={})
    content = MinimalistSettingsContent(controller)

    content.select_section("validation_health")
    content.run_validation_now()
    qapp.processEvents()

    assert not content.save_button.isEnabled()
    assert not content.unsaved_label.isVisible()
    assert not content.dirty_sections
    content.close()


def test_settings_confirmation_dialog_uses_readable_action_labels(qapp) -> None:
    dialog = SettingsConfirmationDialog(
        None,
        "Reset Section",
        "Reset Refresh & Cache settings to defaults? Unsaved edits in this section will be replaced.",
        (
            DialogAction("cancel", "Cancel", "secondary"),
            DialogAction("reset", "Reset Section", "danger"),
        ),
        default_action="cancel",
        cancel_action="cancel",
        theme_preference="dark",
    )
    button_text = {button.text() for button in dialog.findChildren(QPushButton)}

    assert {"Cancel", "Reset Section"}.issubset(button_text)
    assert "Yes" not in button_text
    assert "No" not in button_text
    assert "#f8fbff" in dialog.styleSheet()
    assert "#d7e2f0" in dialog.styleSheet()
    dialog.close()


def test_minimalist_settings_theme_previews_saves_and_discards(qapp, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("EOAT_ATLAS_USER_DATA_DIR", str(tmp_path / "user_data"))
    previews: list[str] = []
    committed: list[dict] = []
    controller = SimpleNamespace(
        config=UserConfig(project_root=str(tmp_path)),
        minimalist_app_settings={},
        preview_minimalist_theme=lambda value, **_kwargs: previews.append(value),
        commit_minimalist_settings=lambda settings: committed.append(deepcopy(settings)),
    )
    content = MinimalistSettingsContent(controller)
    content.resize(1400, 900)
    content.show()
    qapp.processEvents()

    assert content.saved_settings["app"]["theme"] == "dark"

    content.select_section("display_accessibility")
    content._start_admin_session()
    content._set_setting("app.theme", "light")
    qapp.processEvents()

    assert content.draft_settings["app"]["theme"] == "light"
    assert content.save_button.isEnabled()
    assert previews[-1] == "light"
    assert "#0c1b2e" in content.styleSheet()

    content.save_current_settings()

    saved = load_settings(content.settings_file)
    assert saved["app"]["theme"] == "light"
    assert committed[-1]["app"]["theme"] == "light"
    assert not content.save_button.isEnabled()

    content._set_setting("app.theme", "dark")
    assert previews[-1] == "dark"
    assert content.save_button.isEnabled()

    content._discard_unsaved_changes()
    qapp.processEvents()

    assert content.draft_settings["app"]["theme"] == "light"
    assert previews[-1] == "light"
    assert not content.save_button.isEnabled()
    content.close()


def test_custom_default_baseline_is_used_by_reset_actions(qapp, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("EOAT_ATLAS_USER_DATA_DIR", str(tmp_path / "user_data"))
    controller = SimpleNamespace(config=UserConfig(project_root=str(tmp_path)), minimalist_app_settings={})
    content = MinimalistSettingsContent(controller)
    content._start_admin_session()
    content._set_setting("library.cards_per_page", 48)
    assert content.save_current_settings()

    monkeypatch.setattr(settings_page_module, "show_settings_confirmation", lambda *args, **kwargs: "set")
    content.set_current_configuration_as_defaults()
    assert get_effective_default_settings(settings_file=content.settings_file)["library"]["cards_per_page"] == 48

    content._set_setting("library.cards_per_page", 12)
    assert content.save_current_settings()
    assert load_settings(content.settings_file)["library"]["cards_per_page"] == 12

    monkeypatch.setattr(settings_page_module, "show_settings_confirmation", lambda *args, **kwargs: "reset")
    content.reset_all_settings()
    qapp.processEvents()

    assert content.draft_settings["library"]["cards_per_page"] == 48
    assert load_settings(content.settings_file)["library"]["cards_per_page"] == 12
    assert content.save_button.isEnabled()
    content.close()


def _widget_text(widget) -> str:
    items = [*widget.findChildren(QLabel), *widget.findChildren(QPushButton)]
    return "\n".join(item.text() for item in items if item.text())


def _setting_combo(content: MinimalistSettingsContent, setting_path: str) -> QComboBox:
    for combo in content.main_panel.findChildren(QComboBox):
        if combo.property("settingPath") == setting_path:
            return combo
    raise AssertionError(f"Missing combo for {setting_path}")


def _setting_checkbox(content: MinimalistSettingsContent, setting_path: str) -> QCheckBox:
    for checkbox in content.findChildren(QCheckBox):
        if checkbox.property("settingPath") == setting_path:
            return checkbox
    raise AssertionError(f"Missing checkbox for {setting_path}")
