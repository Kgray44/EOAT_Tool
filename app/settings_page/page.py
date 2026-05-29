from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import fields
from pathlib import Path
from typing import Any

try:
    from PySide6.QtCore import Signal
    from PySide6.QtWidgets import (
        QCheckBox,
        QComboBox,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QPushButton,
        QScrollArea,
        QTableWidget,
        QTableWidgetItem,
        QTabWidget,
        QVBoxLayout,
        QWidget,
    )
except ImportError:  # pragma: no cover
    Signal = None
    QCheckBox = QComboBox = QHBoxLayout = QLabel = QLineEdit = QPushButton = QScrollArea = QTabWidget = QTableWidget = QTableWidgetItem = QVBoxLayout = QWidget = None

from app.settings_page.advanced_section import build_advanced_section
from app.settings_page.audit_defaults_section import build_audit_defaults_section
from app.settings_page.backups_section import build_backups_section
from app.settings_page.external_tools_section import build_external_tools_section
from app.settings_page.models import (
    DEFAULT_AUDIT_SETTING_VALUES,
    DEFAULT_CONNECTION_SETTING_VALUES,
    SETTINGS_SECTION_TITLES,
)
from app.settings_page.project_section import build_project_section
from app.settings_page.scheduled_reports_section import build_scheduled_reports_section
from app.settings_page.smart_rules_section import build_smart_rules_section
from app.settings_page.ui_preferences_section import build_ui_preferences_section
from app.settings_page.widgets import add_stretch, settings_tab
from app.task_runner import TaskRequest, get_task_manager
from app.widgets.file_picker import select_directory, select_file
from core.audit.default_rules import (
    ALLOWED_SCOPES,
    OVERWRITE_POLICIES,
    audit_default_rules_from_config,
    default_rules_from_audit_defaults,
    normalize_default_rules,
)
from core.audit.default_rules import (
    preview_audit_default_rules as build_audit_default_preview,
)
from core.config import UserConfig
from core.constants import DEFAULT_CONFIG_PATH
from core.git_activity import find_git_executable, is_git_repo
from core.logging import log_tool_run
from core.openers import open_path
from core.paths import resolve_project_paths
from core.project_backup import backup_project
from core.project_root_status import validate_project_root
from core.result import ToolResult
from core.safe_files import ensure_directory
from core.scheduled_reports import install_or_repair_schedules, scheduled_tools_log_path
from core.settings_schema import (
    CURRENT_CONFIG_SCHEMA_VERSION,
    default_backups_config,
    default_scheduled_reports_config,
    default_ui_preferences_config,
)
from core.settings_validation import validate_settings_payload
from core.system_audit import run_system_audit
from core.validation import validate_project_foundation


class SettingsPage(QWidget):
    settings_saved = Signal()
    theme_changed = Signal(str)

    def __init__(
        self,
        config: UserConfig,
        parent=None,
        *,
        config_loader: Callable[[], UserConfig] | None = None,
        config_saver: Callable[[UserConfig], Path] | None = None,
        path_opener: Callable[[Path], ToolResult] | None = None,
    ):
        super().__init__(parent)
        self.config = config
        self._load_config = config_loader
        self._save_config = config_saver
        self._open_path = path_opener or open_path
        self._searchable_sections = []
        self._dirty = False
        self._baseline_payload: dict[str, Any] = {}
        self.audit_default_edits: dict[str, QLineEdit] = {}
        self.connection_default_edits: dict[str, QLineEdit] = {}

        self.config_path_label = QLabel(str(DEFAULT_CONFIG_PATH))
        self.config_path_label.setWordWrap(True)
        self.project_root_edit = QLineEdit(config.project_root)
        self.project_mode_label = QLabel()
        self.project_mode_label.setWordWrap(True)
        self.master_workbook_label = QLabel()
        self.master_workbook_label.setWordWrap(True)
        self.project_help_label = QLabel("Project paths are stored in local config. Workbook data stays local-first.")
        self.project_help_label.setWordWrap(True)
        self.git_edit = QLineEdit(config.git_executable)
        self.debug_check = QCheckBox()
        self.debug_check.setChecked(config.debug_mode)
        self.theme_combo = QComboBox()
        self.theme_combo.addItem("Light", "light")
        self.theme_combo.addItem("Dark", "dark")
        theme_index = self.theme_combo.findData((config.theme or "light").lower())
        self.theme_combo.setCurrentIndex(theme_index if theme_index >= 0 else 0)
        self.theme_combo.currentIndexChanged.connect(self.theme_preview_changed)
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)

        layout = QVBoxLayout(self)
        heading = QLabel("Settings")
        heading.setStyleSheet("font-size: 18pt; font-weight: 600;")
        layout.addWidget(heading)

        search_row = QHBoxLayout()
        self.settings_search_edit = QLineEdit()
        self.settings_search_edit.setPlaceholderText("Search settings")
        self.settings_search_edit.textChanged.connect(self.apply_settings_search)
        self.dirty_label = QLabel("Saved")
        self.dirty_label.setObjectName("SettingsDirtyLabel")
        search_row.addWidget(QLabel("Search"))
        search_row.addWidget(self.settings_search_edit, stretch=1)
        search_row.addWidget(self.dirty_label)
        layout.addLayout(search_row)

        action_row = QHBoxLayout()
        for label, callback in [
            ("Save Settings", self.save),
            ("Revert Changes", self.revert_changes),
            ("Show Changes", self.show_changes),
        ]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            action_row.addWidget(button)
        action_row.addStretch(1)
        layout.addLayout(action_row)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        scroll.setWidget(content)
        layout.addWidget(scroll, stretch=1)

        self.settings_tabs = QTabWidget()
        content_layout.addWidget(self.settings_tabs)
        tab_layouts = {}
        for title in SETTINGS_SECTION_TITLES:
            tab, tab_layout = settings_tab()
            self.settings_tabs.addTab(tab, title)
            tab_layouts[title] = tab_layout

        build_project_section(self, tab_layouts["Project & Data"])
        build_audit_defaults_section(self, tab_layouts["Audit Defaults"])
        build_smart_rules_section(self, tab_layouts["Smart Rules"])
        build_scheduled_reports_section(self, tab_layouts["Scheduled Reports"])
        build_backups_section(self, tab_layouts["Backups & Safety"])
        build_ui_preferences_section(self, tab_layouts["UI Preferences"])
        build_external_tools_section(self, tab_layouts["External Tools"])
        build_advanced_section(self, tab_layouts["Advanced / Diagnostics"])
        for tab_layout in tab_layouts.values():
            add_stretch(tab_layout)

        self._connect_dirty_tracking()
        self._baseline_payload = self._collect_payload()
        self._set_dirty(False)
        self.update_project_status_labels()

    def _connect_dirty_tracking(self) -> None:
        for edit in self.findChildren(QLineEdit):
            if edit is self.settings_search_edit:
                continue
            edit.textChanged.connect(lambda *_args: self._update_dirty_from_snapshot())
        for check in self.findChildren(QCheckBox):
            check.toggled.connect(lambda *_args: self._update_dirty_from_snapshot())
        for combo in self.findChildren(QComboBox):
            combo.currentIndexChanged.connect(lambda *_args: self._update_dirty_from_snapshot())
        for table in self.findChildren(QTableWidget):
            table.itemChanged.connect(lambda *_args: self._update_dirty_from_snapshot())

    def _set_dirty(self, dirty: bool) -> None:
        self._dirty = bool(dirty)
        self.dirty_label.setText("Unsaved changes" if self._dirty else "Saved")

    def _update_dirty_from_snapshot(self) -> None:
        self._set_dirty(self._collect_payload() != self._baseline_payload)

    def has_unsaved_changes(self) -> bool:
        return bool(self._dirty)

    def can_close(self, destination_page: str | None = None) -> tuple[bool, str]:
        if self.has_unsaved_changes():
            return False, "Settings has unsaved changes. Save or revert settings before leaving."
        return True, ""

    def apply_settings_search(self, query: str = "") -> None:
        needle = str(query or "").strip().casefold()
        first_match_tab = -1
        for group in self._searchable_sections:
            text = " ".join(
                [
                    group.title(),
                    str(group.property("settings_keywords") or ""),
                    " ".join(label.text() for label in group.findChildren(QLabel)),
                ]
            ).casefold()
            visible = not needle or needle in text
            group.setVisible(visible)
            if visible:
                tab_index = self._tab_index_for_child(group)
                if first_match_tab < 0 and tab_index >= 0:
                    first_match_tab = tab_index
        if needle and first_match_tab >= 0:
            self.settings_tabs.setCurrentIndex(first_match_tab)

    def _tab_index_for_child(self, child: QWidget) -> int:
        for index in range(self.settings_tabs.count()):
            tab = self.settings_tabs.widget(index)
            if child is tab or tab.isAncestorOf(child):
                return index
        return -1

    def _collect_payload(self) -> dict[str, Any]:
        theme = self.theme_combo.currentData() or "light"
        backups = self._collect_backups()
        return {
            "config_schema_version": CURRENT_CONFIG_SCHEMA_VERSION,
            "project_root": self.project_root_edit.text().strip(),
            "git_executable": self.git_edit.text().strip(),
            "debug_mode": self.debug_check.isChecked(),
            "theme": theme,
            "project_start_date": getattr(self.config, "project_start_date", ""),
            "workdays": list(getattr(self.config, "workdays", [])),
            "skip_weekends": bool(getattr(self.config, "skip_weekends", True)),
            "holidays": list(getattr(self.config, "holidays", [])),
            "audit_defaults": {
                **DEFAULT_AUDIT_SETTING_VALUES,
                **{field: edit.text().strip() for field, edit in self.audit_default_edits.items()},
            },
            "audit_default_rules": self._collect_audit_default_rules(),
            "connection_defaults": {
                **DEFAULT_CONNECTION_SETTING_VALUES,
                **{field: edit.text().strip() for field, edit in self.connection_default_edits.items()},
            },
            "scheduled_reports": self._collect_scheduled_reports(),
            "backups": backups,
            "backup_policy": self._legacy_backup_policy(backups),
            "ui_preferences": {
                **default_ui_preferences_config(),
                "theme": theme,
                "show_debug_tools": self.debug_check.isChecked(),
            },
            "audit_coach_exclusions": [item.strip() for item in self.audit_coach_exclusions_edit.text().split(",") if item.strip()],
            "smart_default_rules": list(getattr(self.config, "smart_default_rules", []) or []),
        }

    def _collect_scheduled_reports(self) -> dict[str, Any]:
        return {
            **default_scheduled_reports_config(),
            "daily_enabled": self.daily_reports_check.isChecked(),
            "daily_weekdays": [item.strip() for item in self.daily_weekdays_edit.text().split(",") if item.strip()],
            "daily_time": self.daily_report_time_edit.text().strip(),
            "weekly_enabled": self.weekly_reports_check.isChecked(),
            "weekly_weekday": self.weekly_weekday_combo.currentText(),
            "weekly_time": self.weekly_report_time_edit.text().strip(),
            "timezone": self.schedule_timezone_edit.text().strip() or "America/New_York",
            "duplicate_policy": self.duplicate_policy_combo.currentText(),
            "missed_run_policy": self.missed_run_policy_combo.currentText(),
            "dry_run_folder": self.dry_run_folder_edit.text().strip(),
            "prevent_overwrite": self.prevent_overwrite_check.isChecked(),
        }

    def _collect_backups(self) -> dict[str, Any]:
        return {
            **default_backups_config(),
            "backup_before_audit_save": self.backup_before_audit_save_check.isChecked(),
            "backup_before_compatibility_update": self.backup_before_compatibility_update_check.isChecked(),
            "backup_before_workbook_migration": self.backup_before_migration_check.isChecked(),
            "backup_before_bulk_repair": self.backup_before_repair_check.isChecked(),
            "backup_before_schema_repair": self.backup_before_repair_check.isChecked(),
            "retention_days": self.retention_days_edit.text().strip(),
            "newest_backups_per_workbook": self.newest_backups_per_workbook_edit.text().strip(),
            "keep_milestones": self.keep_milestones_check.isChecked(),
            "cleanup_requires_preview": self.cleanup_requires_preview_check.isChecked(),
            "cleanup_blocked_by_validation_blockers": self.cleanup_blocked_by_validation_check.isChecked(),
            "light_backup_retention_count": self.light_backup_retention_edit.text().strip(),
            "workbook_backup_retention_count": self.workbook_backup_retention_edit.text().strip(),
            "cleanup_requires_validation": self.cleanup_blocked_by_validation_check.isChecked(),
        }

    def _legacy_backup_policy(self, backups: dict[str, Any]) -> dict[str, Any]:
        return {
            "backup_before_workbook_migration": bool(backups.get("backup_before_workbook_migration", True)),
            "backup_before_schema_repair": bool(backups.get("backup_before_schema_repair", True)),
            "light_backup_retention_count": _safe_int(backups.get("light_backup_retention_count"), 10),
            "workbook_backup_retention_count": _safe_int(backups.get("workbook_backup_retention_count"), 20),
            "cleanup_requires_validation": bool(backups.get("cleanup_requires_validation", True)),
        }

    def _populate_audit_default_rules_table(self, config: UserConfig) -> None:
        table = getattr(self, "audit_default_rules_table", None)
        if table is None:
            return
        rules = audit_default_rules_from_config(config)
        table.blockSignals(True)
        try:
            table.setRowCount(0)
            for rule in rules:
                self._append_audit_default_rule_row(rule.to_dict())
            table.resizeColumnsToContents()
        finally:
            table.blockSignals(False)

    def _append_audit_default_rule_row(self, rule: dict[str, Any]) -> int:
        table = self.audit_default_rules_table
        row = table.rowCount()
        table.insertRow(row)
        values = [
            rule.get("id", ""),
            "Yes" if rule.get("enabled", True) else "No",
            rule.get("field", ""),
            rule.get("value", ""),
            rule.get("scope", "new_audit"),
            rule.get("overwrite_policy", "empty_only"),
            json.dumps(rule.get("conditions", []), sort_keys=True),
            rule.get("source", "user"),
            rule.get("note", ""),
        ]
        for column, value in enumerate(values):
            table.setItem(row, column, QTableWidgetItem(str(value)))
        return row

    def _collect_audit_default_rules(self) -> list[dict[str, Any]]:
        table = getattr(self, "audit_default_rules_table", None)
        if table is None:
            return [rule.to_dict() for rule in audit_default_rules_from_config(self.config)]
        rows: list[dict[str, Any]] = []
        for row in range(table.rowCount()):
            conditions_text = self._table_text(table, row, 6)
            try:
                parsed_conditions = json.loads(conditions_text) if conditions_text else []
            except json.JSONDecodeError:
                parsed_conditions = []
            rows.append(
                {
                    "id": self._table_text(table, row, 0) or f"user_default_{row + 1}",
                    "enabled": self._table_text(table, row, 1).casefold() not in {"no", "false", "0", "disabled"},
                    "field": self._table_text(table, row, 2),
                    "value": self._table_text(table, row, 3),
                    "scope": self._table_text(table, row, 4) or "new_audit",
                    "overwrite_policy": self._table_text(table, row, 5) or "empty_only",
                    "conditions": parsed_conditions if isinstance(parsed_conditions, list) else [],
                    "source": self._table_text(table, row, 7) or "user",
                    "note": self._table_text(table, row, 8),
                }
            )
        collected = [rule.to_dict() for rule in normalize_default_rules(rows)]
        edit_values = {field: edit.text().strip() for field, edit in self.audit_default_edits.items()}
        for rule in collected:
            if (
                rule.get("field") in edit_values
                and not rule.get("conditions")
                and rule.get("scope") == "new_audit"
                and rule.get("source") in {"system_default", "legacy_audit_defaults"}
            ):
                rule["value"] = edit_values[str(rule.get("field"))]
        return collected

    def _table_text(self, table: QTableWidget, row: int, column: int) -> str:
        item = table.item(row, column)
        return "" if item is None else item.text().strip()

    def _selected_default_rule_row(self) -> int:
        table = self.audit_default_rules_table
        selected = table.selectionModel().selectedRows() if table.selectionModel() is not None else []
        if selected:
            return selected[0].row()
        return table.currentRow()

    def new_default_rule(self) -> None:
        row = self._append_audit_default_rule_row(
            {
                "id": f"user_default_{self.audit_default_rules_table.rowCount() + 1}",
                "enabled": True,
                "field": "Auditor",
                "value": "",
                "scope": ALLOWED_SCOPES[0],
                "overwrite_policy": OVERWRITE_POLICIES[0],
                "conditions": [],
                "source": "user",
                "note": "",
            }
        )
        self.audit_default_rules_table.selectRow(row)
        self._update_dirty_from_snapshot()

    def edit_selected_default_rule(self) -> None:
        row = self._selected_default_rule_row()
        if row < 0:
            self.status_label.setText("Select a default rule to edit.")
            return
        self.audit_default_rules_table.editItem(self.audit_default_rules_table.item(row, 3))
        self.status_label.setText("Editing selected default rule.")

    def duplicate_selected_default_rule(self) -> None:
        row = self._selected_default_rule_row()
        if row < 0:
            self.status_label.setText("Select a default rule to duplicate.")
            return
        rule = self._collect_rule_row(row)
        rule["id"] = f"{rule.get('id') or 'default'}_copy"
        rule["source"] = "user"
        new_row = self._append_audit_default_rule_row(rule)
        self.audit_default_rules_table.selectRow(new_row)
        self._update_dirty_from_snapshot()

    def disable_selected_default_rule(self) -> None:
        row = self._selected_default_rule_row()
        if row < 0:
            self.status_label.setText("Select a default rule to disable.")
            return
        self.audit_default_rules_table.setItem(row, 1, QTableWidgetItem("No"))
        self._update_dirty_from_snapshot()

    def delete_selected_default_rule(self) -> None:
        row = self._selected_default_rule_row()
        if row < 0:
            self.status_label.setText("Select a default rule to delete.")
            return
        self.audit_default_rules_table.removeRow(row)
        self._update_dirty_from_snapshot()

    def move_selected_default_rule_up(self) -> None:
        self._move_selected_default_rule(-1)

    def move_selected_default_rule_down(self) -> None:
        self._move_selected_default_rule(1)

    def _move_selected_default_rule(self, offset: int) -> None:
        table = self.audit_default_rules_table
        row = self._selected_default_rule_row()
        target = row + offset
        if row < 0 or target < 0 or target >= table.rowCount():
            return
        current = self._collect_rule_row(row)
        other = self._collect_rule_row(target)
        table.blockSignals(True)
        try:
            self._set_rule_row(row, other)
            self._set_rule_row(target, current)
        finally:
            table.blockSignals(False)
        table.selectRow(target)
        self._update_dirty_from_snapshot()

    def _collect_rule_row(self, row: int) -> dict[str, Any]:
        try:
            conditions = json.loads(self._table_text(self.audit_default_rules_table, row, 6) or "[]")
        except json.JSONDecodeError:
            conditions = []
        return {
            "id": self._table_text(self.audit_default_rules_table, row, 0),
            "enabled": self._table_text(self.audit_default_rules_table, row, 1).casefold() not in {"no", "false", "0", "disabled"},
            "field": self._table_text(self.audit_default_rules_table, row, 2),
            "value": self._table_text(self.audit_default_rules_table, row, 3),
            "scope": self._table_text(self.audit_default_rules_table, row, 4),
            "overwrite_policy": self._table_text(self.audit_default_rules_table, row, 5),
            "conditions": conditions if isinstance(conditions, list) else [],
            "source": self._table_text(self.audit_default_rules_table, row, 7),
            "note": self._table_text(self.audit_default_rules_table, row, 8),
        }

    def _set_rule_row(self, row: int, rule: dict[str, Any]) -> None:
        values = [
            rule.get("id", ""),
            "Yes" if rule.get("enabled", True) else "No",
            rule.get("field", ""),
            rule.get("value", ""),
            rule.get("scope", "new_audit"),
            rule.get("overwrite_policy", "empty_only"),
            json.dumps(rule.get("conditions", []), sort_keys=True),
            rule.get("source", "user"),
            rule.get("note", ""),
        ]
        for column, value in enumerate(values):
            self.audit_default_rules_table.setItem(row, column, QTableWidgetItem(str(value)))

    def preview_audit_default_rules(self) -> None:
        result = build_audit_default_preview({}, self._collect_audit_default_rules(), scope="new_audit")
        rows = [row for row in result.preview_rows if row.status in {"would_apply", "already_set"}]
        if not rows:
            self.status_label.setText("No audit defaults would be applied.")
            return
        lines = [
            f"- {row.field}: {row.default_value} ({row.status})"
            for row in rows[:25]
        ]
        extra = "" if len(rows) <= 25 else f"\n...and {len(rows) - 25} more default rule(s)."
        self.status_label.setText("Preview Applied Defaults:\n" + "\n".join(lines) + extra)

    def reset_system_default_rules(self) -> None:
        table = self.audit_default_rules_table
        table.blockSignals(True)
        try:
            table.setRowCount(0)
            for rule in default_rules_from_audit_defaults(DEFAULT_AUDIT_SETTING_VALUES):
                self._append_audit_default_rule_row(rule)
        finally:
            table.blockSignals(False)
        self._update_dirty_from_snapshot()
        self.status_label.setText("System audit defaults restored in settings. Save Settings to persist them.")

    def export_default_rules(self) -> None:
        path = DEFAULT_CONFIG_PATH.parent / "audit_default_rules_export.json"
        ensure_directory(path.parent)
        path.write_text(json.dumps(self._collect_audit_default_rules(), indent=2), encoding="utf-8")
        self.status_label.setText(f"Exported audit defaults to {path}.")

    def import_default_rules(self) -> None:
        path = DEFAULT_CONFIG_PATH.parent / "audit_default_rules_export.json"
        if not path.exists():
            self.status_label.setText(f"No audit default export found at {path}.")
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            self.status_label.setText(f"Could not import audit defaults: {exc}")
            return
        rules = [rule.to_dict() for rule in normalize_default_rules(data if isinstance(data, list) else [])]
        table = self.audit_default_rules_table
        table.blockSignals(True)
        try:
            table.setRowCount(0)
            for rule in rules:
                self._append_audit_default_rule_row(rule)
        finally:
            table.blockSignals(False)
        self._update_dirty_from_snapshot()
        self.status_label.setText(f"Imported {len(rules)} audit default rule(s).")

    def _payload_to_config(self, payload: dict[str, Any]) -> UserConfig:
        data = dict(getattr(self.config, "extra_config", {}) or {})
        data.update(payload)
        return UserConfig.from_dict(data)

    def _apply_config_to_self(self, config: UserConfig) -> None:
        for field in fields(UserConfig):
            setattr(self.config, field.name, getattr(config, field.name))

    def _apply_config_to_widgets(self, config: UserConfig) -> None:
        self.project_root_edit.setText(config.project_root)
        self.git_edit.setText(config.git_executable)
        self.debug_check.setChecked(config.debug_mode)
        theme_index = self.theme_combo.findData((config.theme or "light").lower())
        self.theme_combo.setCurrentIndex(theme_index if theme_index >= 0 else 0)
        for field, edit in self.audit_default_edits.items():
            edit.setText(str(config.audit_defaults.get(field, DEFAULT_AUDIT_SETTING_VALUES.get(field, ""))))
        self._populate_audit_default_rules_table(config)
        for field, edit in self.connection_default_edits.items():
            edit.setText(str(config.connection_defaults.get(field, DEFAULT_CONNECTION_SETTING_VALUES.get(field, ""))))
        scheduled = {**default_scheduled_reports_config(), **dict(config.scheduled_reports or {})}
        self.daily_reports_check.setChecked(bool(scheduled.get("daily_enabled", True)))
        self.daily_weekdays_edit.setText(", ".join(scheduled.get("daily_weekdays") or default_scheduled_reports_config()["daily_weekdays"]))
        self.daily_report_time_edit.setText(str(scheduled.get("daily_time", "19:00")))
        self.weekly_reports_check.setChecked(bool(scheduled.get("weekly_enabled", True)))
        weekly_index = self.weekly_weekday_combo.findText(str(scheduled.get("weekly_weekday", "Friday")))
        self.weekly_weekday_combo.setCurrentIndex(weekly_index if weekly_index >= 0 else 4)
        self.weekly_report_time_edit.setText(str(scheduled.get("weekly_time", "19:00")))
        self.schedule_timezone_edit.setText(str(scheduled.get("timezone", "America/New_York")))
        duplicate_index = self.duplicate_policy_combo.findText(str(scheduled.get("duplicate_policy", "skip_existing")))
        self.duplicate_policy_combo.setCurrentIndex(duplicate_index if duplicate_index >= 0 else 0)
        missed_index = self.missed_run_policy_combo.findText(str(scheduled.get("missed_run_policy", "catch_up")))
        self.missed_run_policy_combo.setCurrentIndex(missed_index if missed_index >= 0 else 0)
        self.dry_run_folder_edit.setText(str(scheduled.get("dry_run_folder", "")))
        self.prevent_overwrite_check.setChecked(bool(scheduled.get("prevent_overwrite", True)))
        backups = {**default_backups_config(), **dict(config.backups or config.backup_policy or {})}
        self.backup_before_audit_save_check.setChecked(bool(backups.get("backup_before_audit_save", True)))
        self.backup_before_compatibility_update_check.setChecked(bool(backups.get("backup_before_compatibility_update", True)))
        self.backup_before_migration_check.setChecked(bool(backups.get("backup_before_workbook_migration", True)))
        self.backup_before_repair_check.setChecked(bool(backups.get("backup_before_bulk_repair", backups.get("backup_before_schema_repair", True))))
        self.retention_days_edit.setText(str(backups.get("retention_days", 7)))
        self.newest_backups_per_workbook_edit.setText(str(backups.get("newest_backups_per_workbook", 25)))
        self.keep_milestones_check.setChecked(bool(backups.get("keep_milestones", True)))
        self.cleanup_requires_preview_check.setChecked(bool(backups.get("cleanup_requires_preview", True)))
        self.cleanup_blocked_by_validation_check.setChecked(bool(backups.get("cleanup_blocked_by_validation_blockers", True)))
        self.light_backup_retention_edit.setText(str(backups.get("light_backup_retention_count", 10)))
        self.workbook_backup_retention_edit.setText(str(backups.get("workbook_backup_retention_count", 20)))
        self.audit_coach_exclusions_edit.setText(", ".join(config.audit_coach_exclusions))

    def save(self) -> None:
        payload = self._collect_payload()
        validation = validate_settings_payload(payload)
        if not validation.ok:
            self.status_label.setText("Settings not saved.\n" + "\n".join(f"- {error}" for error in validation.errors))
            self._set_dirty(True)
            return
        old_root = self.config.project_root
        new_config = self._payload_to_config(payload)
        self._apply_config_to_self(new_config)
        path = self._save_config(self.config) if self._save_config is not None else DEFAULT_CONFIG_PATH
        root_status = validate_project_root(self.config.project_root)
        validation_result = validate_project_foundation(self.config.project_root) if root_status.is_usable else None
        warnings = list(root_status.missing_items)
        if validation_result is not None:
            warnings.extend(validation_result.warnings)
        result = ToolResult.ok(
            "settings",
            "Settings",
            "Settings saved.",
            details=[
                f"Config file: {path}",
                f"Project root: {self.config.project_root}",
                f"Data mode: {root_status.mode_label}",
                f"Master workbook: {root_status.master_workbook}",
                root_status.message,
            ],
            warnings=warnings,
        )
        if old_root != self.config.project_root and Path(self.config.project_root).exists():
            warning = log_tool_run(result, self.config.project_root)
            if warning:
                result.warnings.append(warning)
        self.status_label.setText(result.to_markdown())
        self.update_project_status_labels()
        self._baseline_payload = self._collect_payload()
        self._set_dirty(False)
        self.settings_saved.emit()
        self.theme_changed.emit(self.config.theme)

    def reload(self) -> None:
        if self._load_config is None:
            self.revert_changes()
            return
        loaded = self._load_config()
        self._apply_config_to_self(loaded)
        self._apply_config_to_widgets(self.config)
        self.update_project_status_labels()
        self._baseline_payload = self._collect_payload()
        self._set_dirty(False)
        self.status_label.setText("Settings reloaded from disk.")
        self.settings_saved.emit()
        self.theme_changed.emit(self.config.theme)

    def revert_changes(self) -> None:
        config = self._payload_to_config(self._baseline_payload)
        self._apply_config_to_widgets(config)
        self.update_project_status_labels()
        self._set_dirty(False)
        self.status_label.setText("Settings reverted to the last saved baseline.")

    def show_changes(self) -> None:
        current = self._collect_payload()
        changes = []
        for key in sorted(set(current) | set(self._baseline_payload)):
            if current.get(key) != self._baseline_payload.get(key):
                changes.append(f"- {key}: {json.dumps(self._baseline_payload.get(key), sort_keys=True)} -> {json.dumps(current.get(key), sort_keys=True)}")
        self.status_label.setText("No settings changes." if not changes else "Pending settings changes:\n" + "\n".join(changes))

    def browse_project_root(self) -> None:
        selected = select_directory(self, "Select EOAT Project Root", self.project_root_edit.text())
        if selected:
            self.project_root_edit.setText(selected)
            self.update_project_status_labels()

    def browse_git(self) -> None:
        selected = select_file(self, "Select Git Executable", self.git_edit.text())
        if selected:
            self.git_edit.setText(selected)

    def test_git(self) -> None:
        git_path, warning = find_git_executable(self.git_edit.text())
        if warning:
            self.status_label.setText(warning)
            return
        repo, repo_warning = is_git_repo(self.project_root_edit.text(), git_path)
        suffix = "Git repo detected." if repo else f"Git executable works; repo not detected. {repo_warning or ''}"
        self.status_label.setText(f"Git executable: {git_path}\n{suffix}")

    def update_project_status_labels(self) -> None:
        status = validate_project_root(self.project_root_edit.text())
        self.project_mode_label.setText(f"{status.mode_label}: {status.message}")
        self.master_workbook_label.setText(str(status.master_workbook))

    def theme_preview_changed(self) -> None:
        self.theme_changed.emit(self.theme_combo.currentData() or "light")

    def run_system_audit(self) -> None:
        self._run_background(
            "settings_system_audit",
            "Full System Audit",
            lambda: run_system_audit(self.project_root_edit.text(), check_cli_help=False),
        )

    def backup_workbook(self) -> None:
        self._run_background(
            "settings_backup_workbook",
            "Workbook Backup",
            lambda: backup_project(self.project_root_edit.text(), mode="workbook"),
            modifies_files=True,
            workbook_lock=True,
        )

    def backup_light(self) -> None:
        self._run_background(
            "settings_backup_light",
            "Light Project Backup",
            lambda: backup_project(self.project_root_edit.text(), mode="light"),
            modifies_files=True,
        )

    def install_or_repair_scheduled_tasks(self) -> None:
        self._run_background(
            "settings_install_scheduled_reports",
            "Install/Repair Scheduled Reports",
            lambda: install_or_repair_schedules(self.project_root_edit.text()),
            modifies_files=True,
        )

    def open_scheduled_reports_page(self) -> None:
        self.status_label.setText("Scheduled Reports page can be opened from the left navigation.")

    def open_backup_manager_page(self) -> None:
        self.status_label.setText("Backup Manager page can be opened from the left navigation.")

    def open_scheduled_log(self) -> None:
        result = self._open_path(scheduled_tools_log_path(self.project_root_edit.text()))
        self.status_label.setText(result.to_markdown() if not result.success else "Opened scheduled tool log.")

    def open_backups(self) -> None:
        result = self._open_path(resolve_project_paths(self.project_root_edit.text()).project_admin / "Backups")
        self.status_label.setText(result.to_markdown() if not result.success else "Opened backups folder.")

    def _run_background(self, task_id: str, name: str, func, modifies_files: bool = False, workbook_lock: bool = False) -> None:
        self.status_label.setText(f"Running: {name}...")
        get_task_manager().run_task(
            TaskRequest(
                id=task_id,
                name=name,
                category="settings",
                callable=func,
                modifies_files=modifies_files,
                requires_workbook_lock=workbook_lock,
                requires_project_lock=modifies_files,
            ),
            on_finished=lambda result: self.status_label.setText(result.to_markdown()),
        )


__all__ = ["SettingsPage"]


def _safe_int(value: Any, fallback: int) -> int:
    try:
        parsed = int(str(value or "").strip())
    except ValueError:
        return fallback
    return parsed if parsed >= 0 else fallback
