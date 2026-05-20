from __future__ import annotations

from pathlib import Path

try:
    from PySide6.QtCore import Signal
    from PySide6.QtWidgets import QCheckBox, QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget
except ImportError:  # pragma: no cover
    Signal = None
    QCheckBox = QComboBox = QFormLayout = QGroupBox = QHBoxLayout = QLabel = QLineEdit = QPushButton = QScrollArea = QVBoxLayout = QWidget = None

from app.widgets.file_picker import select_directory, select_file
from app.task_runner import TaskRequest, get_task_manager
from core.config import load_config, save_config
from core.constants import DEFAULT_CONFIG_PATH
from core.git_activity import find_git_executable, is_git_repo
from core.logging import log_tool_run
from core.openers import open_path
from core.paths import resolve_project_paths
from core.project_backup import backup_project
from core.result import ToolResult
from core.system_audit import run_system_audit
from core.validation import validate_project_foundation


class SettingsPage(QWidget):
    settings_saved = Signal()
    theme_changed = Signal(str)

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.config_path_label = QLabel(str(DEFAULT_CONFIG_PATH))
        self.config_path_label.setWordWrap(True)
        self.project_root_edit = QLineEdit(config.project_root)
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

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        scroll.setWidget(content)
        layout.addWidget(scroll, stretch=1)

        project_box = QGroupBox("Project Configuration")
        project_layout = QVBoxLayout(project_box)
        project_layout.addWidget(QLabel("Config file"))
        project_layout.addWidget(self.config_path_label)

        form = QFormLayout()
        project_row = QHBoxLayout()
        project_row.addWidget(self.project_root_edit)
        project_button = QPushButton("Browse")
        project_button.clicked.connect(self.browse_project_root)
        project_row.addWidget(project_button)
        form.addRow("Project root", project_row)
        project_layout.addLayout(form)
        content_layout.addWidget(project_box)

        tools_box = QGroupBox("Git / External Tools")
        tools_form = QFormLayout(tools_box)
        git_row = QHBoxLayout()
        git_row.addWidget(self.git_edit)
        git_button = QPushButton("Browse")
        git_button.clicked.connect(self.browse_git)
        git_row.addWidget(git_button)
        tools_form.addRow("Git executable", git_row)
        content_layout.addWidget(tools_box)

        ui_box = QGroupBox("UI Preferences")
        ui_form = QFormLayout(ui_box)
        ui_form.addRow("Debug mode", self.debug_check)
        ui_form.addRow("Theme", self.theme_combo)
        content_layout.addWidget(ui_box)

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
        content_layout.addWidget(checks_box)
        content_layout.addStretch(1)

    def browse_project_root(self) -> None:
        selected = select_directory(self, "Select EOAT Project Root", self.project_root_edit.text())
        if selected:
            self.project_root_edit.setText(selected)

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
        path = save_config(self.config)
        validation = validate_project_foundation(self.config.project_root)
        result = ToolResult.ok(
            "settings",
            "Settings",
            "Settings saved.",
            details=[f"Config file: {path}", f"Project root: {self.config.project_root}"],
            warnings=validation.warnings[:],
        )
        if old_root != self.config.project_root and Path(self.config.project_root).exists():
            warning = log_tool_run(result, self.config.project_root)
            if warning:
                result.warnings.append(warning)
        self.status_label.setText(result.to_markdown())
        self.settings_saved.emit()
        self.theme_changed.emit(self.config.theme)

    def reload(self) -> None:
        loaded = load_config()
        self.config.project_root = loaded.project_root
        self.config.git_executable = loaded.git_executable
        self.config.debug_mode = loaded.debug_mode
        self.config.theme = loaded.theme
        self.project_root_edit.setText(loaded.project_root)
        self.git_edit.setText(loaded.git_executable)
        self.debug_check.setChecked(loaded.debug_mode)
        theme_index = self.theme_combo.findData((loaded.theme or "light").lower())
        self.theme_combo.setCurrentIndex(theme_index if theme_index >= 0 else 0)
        self.status_label.setText("Settings reloaded from disk.")
        self.settings_saved.emit()
        self.theme_changed.emit(self.config.theme)

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
