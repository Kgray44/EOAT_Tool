from __future__ import annotations

try:
    from PySide6.QtWidgets import QFormLayout, QLineEdit
except ImportError:  # pragma: no cover
    QFormLayout = QLineEdit = None

from .models import (
    AUDIT_DEFAULT_SETTING_FIELDS,
    CONNECTION_DEFAULT_SETTING_FIELDS,
    DEFAULT_AUDIT_SETTING_VALUES,
    DEFAULT_CONNECTION_SETTING_VALUES,
)
from .widgets import settings_group


def build_audit_defaults_section(page, layout) -> None:
    defaults_group, defaults_layout = settings_group(page, "Audit Defaults", "audit defaults default field values")
    defaults_form = QFormLayout()
    defaults_layout.addLayout(defaults_form)
    for field_name in AUDIT_DEFAULT_SETTING_FIELDS:
        edit = QLineEdit(str(page.config.audit_defaults.get(field_name, DEFAULT_AUDIT_SETTING_VALUES.get(field_name, ""))))
        page.audit_default_edits[field_name] = edit
        defaults_form.addRow(field_name, edit)
    layout.addWidget(defaults_group)

    connection_group, connection_layout = settings_group(page, "Connection Defaults", "connection defaults changeover smart rules")
    connection_form = QFormLayout()
    connection_layout.addLayout(connection_form)
    for field_name in CONNECTION_DEFAULT_SETTING_FIELDS:
        edit = QLineEdit(str(page.config.connection_defaults.get(field_name, DEFAULT_CONNECTION_SETTING_VALUES.get(field_name, ""))))
        page.connection_default_edits[field_name] = edit
        connection_form.addRow(f"{field_name} changeover difficulty", edit)
    layout.addWidget(connection_group)
