from __future__ import annotations

from pathlib import Path

try:
    from PySide6.QtCore import Signal
    from PySide6.QtWidgets import QCheckBox, QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea, QTabWidget, QVBoxLayout, QWidget
except ImportError:  # pragma: no cover
    Signal = None
    QCheckBox = QComboBox = QFormLayout = QGroupBox = QHBoxLayout = QLabel = QLineEdit = QPushButton = QScrollArea = QTabWidget = QVBoxLayout = QWidget = None

from app.widgets.file_picker import select_directory, select_file
from app.task_runner import TaskRequest, get_task_manager
from core.audit.defaults import DEFAULT_AUDIT_DEFAULTS, DEFAULT_CONNECTION_DEFAULTS
from core.config import load_config, save_config
from core.constants import DEFAULT_CONFIG_PATH
from core.git_activity import find_git_executable, is_git_repo
from core.logging import log_tool_run
from core.openers import open_path
from core.paths import resolve_project_paths
from core.project_root_status import validate_project_root
from core.project_backup import backup_project
from core.result import ToolResult
from core.system_audit import run_system_audit
from core.validation import validate_project_foundation

AUDIT_DEFAULT_SETTING_FIELDS = [
    "Auditor",
    "Plant/Area",
    "Cleanroom/Non-Cleanroom",
    "Status",
    "Priority",
    "Follow-Up Needed",
    "Quick Disconnects Present?",
    "Pneumatic Quick Disconnect Type",
    "Vacuum Generator Type",
    "EOAT Interchangeable Circuits",
    "Robot Interchangeable Circuits",
    "Photos Taken?",
]

CONNECTION_DEFAULT_SETTING_FIELDS = ["ATI", "DoveTail"]


def _positive_int(value: str, fallback: int) -> int:
    try:
        parsed = int(str(value or "").strip())
    except ValueError:
        return fallback
    return parsed if parsed >= 0 else fallback


class SettingsPage(QWidget):
    settings_saved = Signal()
    theme_changed = Signal(str)

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.config_path_label = QLabel(str(DEFAULT_CONFIG_PATH))
        self.config_path_label.setWordWrap(True)
        self.project_root_edit = QLineEdit(config.project_root)
        self.project_mode_label = QLabel()
        self.project_mode_label.setWordWrap(True)
        self.master_workbook_label = QLabel()
        self.master_workbook_label.setWordWrap(True)
        self.project_help_label = QLabel(
            "Real project files stay outside GitHub. The selected root is saved only in ignored local config. Demo data is for tests and screenshots."
        )
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
        self.audit_default_edits: dict[str, QLineEdit] = {}
        self.connection_default_edits: dict[str, QLineEdit] = {}

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

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        scroll.setWidget(content)
        layout.addWidget(scroll, stretch=1)

        self._dirty = False
        self._searchable_sections: list[QGroupBox] = []
        self.settings_tabs = QTabWidget()
        content_layout.addWidget(self.settings_tabs)

        project_tab, project_tab_layout = self._settings_tab("Project & Data")
        defaults_tab, defaults_tab_layout = self._settings_tab("Audit Defaults")
        rules_tab, rules_tab_layout = self._settings_tab("Smart Rules")
        scheduled_tab, scheduled_tab_layout = self._settings_tab("Scheduled Reports")
        backups_tab, backups_tab_layout = self._settings_tab("Backups & Safety")
        ui_tools_tab, ui_tools_tab_layout = self._settings_tab("UI & Tools")
        diagnostics_tab, diagnostics_tab_layout = self._settings_tab("Diagnostics")
        for label, tab in [
            ("Project & Data", project_tab),
            ("Audit Defaults", defaults_tab),
            ("Smart Rules", rules_tab),
            ("Scheduled Reports", scheduled_tab),
            ("Backups & Safety", backups_tab),
            ("UI & Tools", ui_tools_tab),
            ("Diagnostics", diagnostics_tab),
        ]:
            self.settings_tabs.addTab(tab, label)

        project_box = QGroupBox("Project Configuration")
        project_layout = QVBoxLayout(project_box)
        project_layout.addWidget(QLabel("Config file"))
        project_layout.addWidget(self.config_path_label)

        form = QFormLayout()
        project_row = QHBoxLayout()
        project_row.addWidget(self.project_root_edit)
        project_button = QPushButton("Choose Real Project Folder")
        project_button.clicked.connect(self.browse_project_root)
        project_row.addWidget(project_button)
        form.addRow("Project root", project_row)
        project_layout.addLayout(form)
        project_layout.addWidget(QLabel("Data mode"))
        project_layout.addWidget(self.project_mode_label)
        project_layout.addWidget(QLabel("Master workbook path"))
        project_layout.addWidget(self.master_workbook_label)
        project_layout.addWidget(self.project_help_label)
        self._register_settings_section(project_box, "project data root workbook mode")
        project_tab_layout.addWidget(project_box)

        tools_box = QGroupBox("Git / External Tools")
        tools_form = QFormLayout(tools_box)
        git_row = QHBoxLayout()
        git_row.addWidget(self.git_edit)
        git_button = QPushButton("Browse")
        git_button.clicked.connect(self.browse_git)
        git_row.addWidget(git_button)
        tools_form.addRow("Git executable", git_row)
        self._register_settings_section(tools_box, "git external tools executable")
        ui_tools_tab_layout.addWidget(tools_box)

        ui_box = QGroupBox("UI Preferences")
        ui_form = QFormLayout(ui_box)
        ui_form.addRow("Debug mode", self.debug_check)
        ui_form.addRow("Theme", self.theme_combo)
        self._register_settings_section(ui_box, "ui preferences theme debug")
        ui_tools_tab_layout.addWidget(ui_box)

        audit_defaults_box = QGroupBox("Audit Defaults")
        audit_defaults_form = QFormLayout(audit_defaults_box)
        for field_name in AUDIT_DEFAULT_SETTING_FIELDS:
            edit = QLineEdit(str(config.audit_defaults.get(field_name, DEFAULT_AUDIT_DEFAULTS.get(field_name, ""))))
            self.audit_default_edits[field_name] = edit
            audit_defaults_form.addRow(field_name, edit)
        self._register_settings_section(audit_defaults_box, "audit defaults default field values")
        defaults_tab_layout.addWidget(audit_defaults_box)

        connection_defaults_box = QGroupBox("Connection Defaults")
        connection_defaults_form = QFormLayout(connection_defaults_box)
        for field_name in CONNECTION_DEFAULT_SETTING_FIELDS:
            edit = QLineEdit(str(config.connection_defaults.get(field_name, DEFAULT_CONNECTION_DEFAULTS.get(field_name, ""))))
            self.connection_default_edits[field_name] = edit
            connection_defaults_form.addRow(f"{field_name} changeover difficulty", edit)
        self._register_settings_section(connection_defaults_box, "connection defaults changeover smart rules")
        defaults_tab_layout.addWidget(connection_defaults_box)

        scheduled_box = QGroupBox("Scheduled Reports")
        scheduled_layout = QFormLayout(scheduled_box)
        scheduled_config = dict(getattr(config, "scheduled_reports", {}))
        self.daily_reports_check = QCheckBox()
        self.daily_reports_check.setChecked(bool(scheduled_config.get("daily_enabled", True)))
        self.weekly_reports_check = QCheckBox()
        self.weekly_reports_check.setChecked(bool(scheduled_config.get("weekly_enabled", True)))
        self.daily_report_time_edit = QLineEdit(str(scheduled_config.get("daily_time", "19:00")))
        self.weekly_report_time_edit = QLineEdit(str(scheduled_config.get("weekly_time", "19:00")))
        self.schedule_timezone_edit = QLineEdit(str(scheduled_config.get("timezone", "America/New_York")))
        self.prevent_overwrite_check = QCheckBox()
        self.prevent_overwrite_check.setChecked(bool(scheduled_config.get("prevent_overwrite", True)))
        scheduled_layout.addRow("Daily summaries", self.daily_reports_check)
        scheduled_layout.addRow("Weekly summaries", self.weekly_reports_check)
        scheduled_layout.addRow("Daily time", self.daily_report_time_edit)
        scheduled_layout.addRow("Weekly time", self.weekly_report_time_edit)
        scheduled_layout.addRow("Timezone", self.schedule_timezone_edit)
        scheduled_layout.addRow("Prevent overwrite", self.prevent_overwrite_check)
        self._register_settings_section(scheduled_box, "scheduled reports daily weekly time no overwrite")
        scheduled_tab_layout.addWidget(scheduled_box)

        safety_box = QGroupBox("Safety / Backups")
        safety_layout = QFormLayout(safety_box)
        backup_policy = dict(getattr(config, "backup_policy", {}))
        self.backup_before_migration_check = QCheckBox()
        self.backup_before_migration_check.setChecked(bool(backup_policy.get("backup_before_workbook_migration", True)))
        self.backup_before_repair_check = QCheckBox()
        self.backup_before_repair_check.setChecked(bool(backup_policy.get("backup_before_schema_repair", True)))
        self.light_backup_retention_edit = QLineEdit(str(backup_policy.get("light_backup_retention_count", 10)))
        self.workbook_backup_retention_edit = QLineEdit(str(backup_policy.get("workbook_backup_retention_count", 20)))
        self.cleanup_requires_validation_check = QCheckBox()
        self.cleanup_requires_validation_check.setChecked(bool(backup_policy.get("cleanup_requires_validation", True)))
        safety_layout.addRow("Backup before migrations", self.backup_before_migration_check)
        safety_layout.addRow("Backup before schema repairs", self.backup_before_repair_check)
        safety_layout.addRow("Light backup retention", self.light_backup_retention_edit)
        safety_layout.addRow("Workbook backup retention", self.workbook_backup_retention_edit)
        safety_layout.addRow("Cleanup requires validation", self.cleanup_requires_validation_check)
        self._register_settings_section(safety_box, "backup safety retention migration repair")
        backups_tab_layout.addWidget(safety_box)

        rules_box = QGroupBox("Audit Coach Rules")
        rules_form = QFormLayout(rules_box)
        self.audit_coach_exclusions_edit = QLineEdit(", ".join(getattr(config, "audit_coach_exclusions", [])))
        rules_form.addRow("Excluded fields", self.audit_coach_exclusions_edit)
        self._register_settings_section(rules_box, "audit coach exclusions rules completion")
        rules_tab_layout.addWidget(rules_box)

        checks_box = QGroupBox("System Checks / Backups")
        checks_layout = QVBoxLayout(checks_box)
        button_row = QHBoxLayout()
        for label, callback in [
            ("Test Git Path", self.test_git),
            ("Save Settings", self.save),
            ("Reload Settings", self.reload),
            ("Run Full System Audit", self.run_system_audit),
            ("Backup Workbook", self.backup_workbook),
            ("Create Light Project Backup", self.backup_light),
            ("Open Backups Folder", self.open_backups),
        ]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            button_row.addWidget(button)
        checks_layout.addLayout(button_row)
        checks_layout.addWidget(self.status_label)
        self._register_settings_section(checks_box, "system checks backups diagnostics audit")
        diagnostics_tab_layout.addWidget(checks_box)
        for tab_layout in [
            project_tab_layout,
            defaults_tab_layout,
            rules_tab_layout,
            scheduled_tab_layout,
            backups_tab_layout,
            ui_tools_tab_layout,
            diagnostics_tab_layout,
        ]:
            tab_layout.addStretch(1)
        self._connect_dirty_tracking()
        self._set_dirty(False)
        self.update_project_status_labels()

    def _settings_tab(self, _label: str) -> tuple[QWidget, QVBoxLayout]:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        return tab, layout

    def _register_settings_section(self, box: QGroupBox, keywords: str) -> None:
        box.setProperty("settings_keywords", keywords)
        self._searchable_sections.append(box)

    def _connect_dirty_tracking(self) -> None:
        for edit in self.findChildren(QLineEdit):
            if edit is self.settings_search_edit:
                continue
            edit.textChanged.connect(lambda *_args: self._set_dirty(True))
        for check in self.findChildren(QCheckBox):
            check.toggled.connect(lambda *_args: self._set_dirty(True))
        for combo in self.findChildren(QComboBox):
            combo.currentIndexChanged.connect(lambda *_args: self._set_dirty(True))

    def _set_dirty(self, dirty: bool) -> None:
        self._dirty = dirty
        if hasattr(self, "dirty_label"):
            self.dirty_label.setText("Unsaved changes" if dirty else "Saved")

    def has_unsaved_changes(self) -> bool:
        return bool(getattr(self, "_dirty", False))

    def can_close(self) -> tuple[bool, str]:
        if self.has_unsaved_changes():
            return False, "Settings has unsaved changes. Save or reload settings before leaving."
        return True, ""

    def apply_settings_search(self, query: str = "") -> None:
        needle = str(query or "").strip().casefold()
        first_match_tab = -1
        for box in self._searchable_sections:
            text = " ".join(
                [
                    box.title(),
                    str(box.property("settings_keywords") or ""),
                    " ".join(label.text() for label in box.findChildren(QLabel)),
                ]
            ).casefold()
            visible = not needle or needle in text
            box.setVisible(visible)
            if visible:
                tab_index = self._tab_index_for_child(box)
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

    def save(self) -> None:
        old_root = self.config.project_root
        self.config.project_root = self.project_root_edit.text()
        self.config.git_executable = self.git_edit.text()
        self.config.debug_mode = self.debug_check.isChecked()
        self.config.theme = self.theme_combo.currentData() or "light"
        self.config.audit_defaults = {
            **DEFAULT_AUDIT_DEFAULTS,
            **{field: edit.text().strip() for field, edit in self.audit_default_edits.items()},
        }
        self.config.connection_defaults = {
            **DEFAULT_CONNECTION_DEFAULTS,
            **{field: edit.text().strip() for field, edit in self.connection_default_edits.items()},
        }
        self.config.scheduled_reports = {
            "daily_enabled": self.daily_reports_check.isChecked(),
            "weekly_enabled": self.weekly_reports_check.isChecked(),
            "daily_time": self.daily_report_time_edit.text().strip() or "19:00",
            "weekly_time": self.weekly_report_time_edit.text().strip() or "19:00",
            "timezone": self.schedule_timezone_edit.text().strip() or "America/New_York",
            "prevent_overwrite": self.prevent_overwrite_check.isChecked(),
        }
        self.config.backup_policy = {
            "backup_before_workbook_migration": self.backup_before_migration_check.isChecked(),
            "backup_before_schema_repair": self.backup_before_repair_check.isChecked(),
            "light_backup_retention_count": _positive_int(self.light_backup_retention_edit.text(), 10),
            "workbook_backup_retention_count": _positive_int(self.workbook_backup_retention_edit.text(), 20),
            "cleanup_requires_validation": self.cleanup_requires_validation_check.isChecked(),
        }
        self.config.audit_coach_exclusions = [item.strip() for item in self.audit_coach_exclusions_edit.text().split(",") if item.strip()]
        path = save_config(self.config)
        root_status = validate_project_root(self.config.project_root)
        validation = validate_project_foundation(self.config.project_root) if root_status.is_usable else None
        warnings = list(root_status.missing_items)
        if validation is not None:
            warnings.extend(validation.warnings)
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
        self._set_dirty(False)
        self.settings_saved.emit()
        self.theme_changed.emit(self.config.theme)

    def reload(self) -> None:
        loaded = load_config()
        self.config.project_root = loaded.project_root
        self.config.git_executable = loaded.git_executable
        self.config.debug_mode = loaded.debug_mode
        self.config.theme = loaded.theme
        self.config.audit_defaults = loaded.audit_defaults
        self.config.connection_defaults = loaded.connection_defaults
        self.config.scheduled_reports = loaded.scheduled_reports
        self.config.backup_policy = loaded.backup_policy
        self.config.audit_coach_exclusions = loaded.audit_coach_exclusions
        self.config.smart_default_rules = loaded.smart_default_rules
        self.project_root_edit.setText(loaded.project_root)
        self.git_edit.setText(loaded.git_executable)
        self.debug_check.setChecked(loaded.debug_mode)
        for field, edit in self.audit_default_edits.items():
            edit.setText(str(self.config.audit_defaults.get(field, DEFAULT_AUDIT_DEFAULTS.get(field, ""))))
        for field, edit in self.connection_default_edits.items():
            edit.setText(str(self.config.connection_defaults.get(field, DEFAULT_CONNECTION_DEFAULTS.get(field, ""))))
        scheduled = dict(self.config.scheduled_reports)
        self.daily_reports_check.setChecked(bool(scheduled.get("daily_enabled", True)))
        self.weekly_reports_check.setChecked(bool(scheduled.get("weekly_enabled", True)))
        self.daily_report_time_edit.setText(str(scheduled.get("daily_time", "19:00")))
        self.weekly_report_time_edit.setText(str(scheduled.get("weekly_time", "19:00")))
        self.schedule_timezone_edit.setText(str(scheduled.get("timezone", "America/New_York")))
        self.prevent_overwrite_check.setChecked(bool(scheduled.get("prevent_overwrite", True)))
        backup_policy = dict(self.config.backup_policy)
        self.backup_before_migration_check.setChecked(bool(backup_policy.get("backup_before_workbook_migration", True)))
        self.backup_before_repair_check.setChecked(bool(backup_policy.get("backup_before_schema_repair", True)))
        self.light_backup_retention_edit.setText(str(backup_policy.get("light_backup_retention_count", 10)))
        self.workbook_backup_retention_edit.setText(str(backup_policy.get("workbook_backup_retention_count", 20)))
        self.cleanup_requires_validation_check.setChecked(bool(backup_policy.get("cleanup_requires_validation", True)))
        self.audit_coach_exclusions_edit.setText(", ".join(self.config.audit_coach_exclusions))
        theme_index = self.theme_combo.findData((loaded.theme or "light").lower())
        self.theme_combo.setCurrentIndex(theme_index if theme_index >= 0 else 0)
        self.status_label.setText("Settings reloaded from disk.")
        self.update_project_status_labels()
        self._set_dirty(False)
        self.settings_saved.emit()
        self.theme_changed.emit(self.config.theme)

    def update_project_status_labels(self) -> None:
        status = validate_project_root(self.project_root_edit.text())
        self.project_mode_label.setText(f"{status.mode_label}: {status.message}")
        self.master_workbook_label.setText(str(status.master_workbook))

    def theme_preview_changed(self) -> None:
        theme = self.theme_combo.currentData() or "light"
        self.config.theme = theme
        self.theme_changed.emit(theme)

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

    def open_backups(self) -> None:
        result = open_path(resolve_project_paths(self.project_root_edit.text()).project_admin / "Backups")
        if not result.success:
            self.status_label.setText(result.to_markdown())

    def _run_background(self, task_id: str, name: str, func, modifies_files: bool = False, workbook_lock: bool = False) -> None:
        self.status_label.setText(f"Running: {name}...")
        manager = get_task_manager()
        manager.run_task(
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
