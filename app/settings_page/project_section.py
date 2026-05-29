from __future__ import annotations

try:
    from PySide6.QtWidgets import QFormLayout, QHBoxLayout, QLabel, QPushButton
except ImportError:  # pragma: no cover
    QFormLayout = QHBoxLayout = QLabel = QPushButton = None

from .widgets import settings_group


def build_project_section(page, layout) -> None:
    group, group_layout = settings_group(page, "Project & Data", "project data root workbook config mode")
    group_layout.addWidget(QLabel("Config file"))
    group_layout.addWidget(page.config_path_label)
    form = QFormLayout()
    project_row = QHBoxLayout()
    project_row.addWidget(page.project_root_edit)
    project_button = QPushButton("Choose Real Project Folder")
    project_button.clicked.connect(page.browse_project_root)
    project_row.addWidget(project_button)
    form.addRow("Project root", project_row)
    group_layout.addLayout(form)
    group_layout.addWidget(QLabel("Data mode"))
    group_layout.addWidget(page.project_mode_label)
    group_layout.addWidget(QLabel("Master workbook path"))
    group_layout.addWidget(page.master_workbook_label)
    group_layout.addWidget(page.project_help_label)
    layout.addWidget(group)
