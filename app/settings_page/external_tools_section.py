from __future__ import annotations

try:
    from PySide6.QtWidgets import QFormLayout, QHBoxLayout, QPushButton
except ImportError:  # pragma: no cover
    QFormLayout = QHBoxLayout = QPushButton = None

from .widgets import settings_group


def build_external_tools_section(page, layout) -> None:
    group, group_layout = settings_group(page, "External Tools", "git external tools executable diagnostics")
    form = QFormLayout()
    git_row = QHBoxLayout()
    git_row.addWidget(page.git_edit)
    browse = QPushButton("Browse")
    browse.clicked.connect(page.browse_git)
    git_row.addWidget(browse)
    test = QPushButton("Test Git Path")
    test.clicked.connect(page.test_git)
    git_row.addWidget(test)
    form.addRow("Git executable", git_row)
    group_layout.addLayout(form)
    layout.addWidget(group)
