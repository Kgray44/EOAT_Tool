from __future__ import annotations

try:
    from PySide6.QtWidgets import QCheckBox, QComboBox, QFormLayout
except ImportError:  # pragma: no cover
    QCheckBox = QComboBox = QFormLayout = None

from .widgets import settings_group


def build_ui_preferences_section(page, layout) -> None:
    group, group_layout = settings_group(page, "UI Preferences", "ui preferences theme debug")
    form = QFormLayout()
    form.addRow("Debug mode", page.debug_check)
    form.addRow("Theme", page.theme_combo)
    group_layout.addLayout(form)
    layout.addWidget(group)
