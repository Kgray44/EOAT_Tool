from __future__ import annotations

try:
    from PySide6.QtWidgets import QFormLayout, QLabel, QLineEdit
except ImportError:  # pragma: no cover
    QFormLayout = QLabel = QLineEdit = None

from .widgets import settings_group


def build_smart_rules_section(page, layout) -> None:
    group, group_layout = settings_group(page, "Smart Rules", "smart rules audit coach defaults exclusions completion")
    form = QFormLayout()
    page.audit_coach_exclusions_edit = QLineEdit(", ".join(getattr(page.config, "audit_coach_exclusions", [])))
    form.addRow("Audit Coach excluded fields", page.audit_coach_exclusions_edit)
    group_layout.addLayout(form)
    count = len(getattr(page.config, "smart_default_rules", []) or [])
    label = QLabel(f"Configured smart default rules: {count}")
    label.setWordWrap(True)
    group_layout.addWidget(label)
    layout.addWidget(group)
