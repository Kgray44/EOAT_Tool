from __future__ import annotations

try:
    from PySide6.QtWidgets import QHBoxLayout, QPushButton, QVBoxLayout
except ImportError:  # pragma: no cover
    QHBoxLayout = QVBoxLayout = QPushButton = None

from .widgets import settings_group


def build_advanced_section(page, layout) -> None:
    group, group_layout = settings_group(
        page, "Advanced / Diagnostics", "advanced diagnostics system audit settings changes"
    )
    button_row = QHBoxLayout()
    for label, callback in [
        ("Run Full System Audit", page.run_system_audit),
        ("Reload Settings", page.reload),
    ]:
        button = QPushButton(label)
        button.clicked.connect(callback)
        button_row.addWidget(button)
    button_row.addStretch(1)
    group_layout.addLayout(button_row)
    group_layout.addWidget(page.status_label)
    layout.addWidget(group)
