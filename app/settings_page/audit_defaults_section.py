from __future__ import annotations

try:
    from PySide6.QtWidgets import (
        QAbstractItemView,
        QFormLayout,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QPushButton,
        QTableWidget,
    )
except ImportError:  # pragma: no cover
    QAbstractItemView = QFormLayout = QHBoxLayout = QLabel = QLineEdit = QPushButton = QTableWidget = None

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
        edit = QLineEdit(
            str(page.config.audit_defaults.get(field_name, DEFAULT_AUDIT_SETTING_VALUES.get(field_name, "")))
        )
        page.audit_default_edits[field_name] = edit
        defaults_form.addRow(field_name, edit)
    layout.addWidget(defaults_group)

    connection_group, connection_layout = settings_group(
        page, "Connection Defaults", "connection defaults changeover smart rules"
    )
    connection_form = QFormLayout()
    connection_layout.addLayout(connection_form)
    for field_name in CONNECTION_DEFAULT_SETTING_FIELDS:
        edit = QLineEdit(
            str(page.config.connection_defaults.get(field_name, DEFAULT_CONNECTION_SETTING_VALUES.get(field_name, "")))
        )
        page.connection_default_edits[field_name] = edit
        connection_form.addRow(f"{field_name} changeover difficulty", edit)
    layout.addWidget(connection_group)

    rules_group, rules_layout = settings_group(
        page, "Default Rules", "default rules new edit duplicate disable delete preview import export reset"
    )
    rules_layout.addWidget(QLabel("Audit Default Manager"))
    page.audit_default_rules_table = QTableWidget(0, 9)
    page.audit_default_rules_table.setHorizontalHeaderLabels(
        ["ID", "Enabled", "Field", "Value", "Scope", "Policy", "Conditions", "Source", "Note"]
    )
    page.audit_default_rules_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    page.audit_default_rules_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    page.audit_default_rules_table.setMinimumHeight(220)
    rules_layout.addWidget(page.audit_default_rules_table)
    page._populate_audit_default_rules_table(page.config)

    first_row = QHBoxLayout()
    second_row = QHBoxLayout()
    for label, callback in [
        ("New Default +", page.new_default_rule),
        ("Edit Selected", page.edit_selected_default_rule),
        ("Duplicate", page.duplicate_selected_default_rule),
        ("Disable", page.disable_selected_default_rule),
        ("Delete", page.delete_selected_default_rule),
        ("Move Up", page.move_selected_default_rule_up),
        ("Move Down", page.move_selected_default_rule_down),
    ]:
        button = QPushButton(label)
        button.clicked.connect(callback)
        first_row.addWidget(button)
    first_row.addStretch(1)
    for label, callback in [
        ("Preview Applied Defaults", page.preview_audit_default_rules),
        ("Import Defaults", page.import_default_rules),
        ("Export Defaults", page.export_default_rules),
        ("Reset System Defaults", page.reset_system_default_rules),
    ]:
        button = QPushButton(label)
        button.clicked.connect(callback)
        second_row.addWidget(button)
    second_row.addStretch(1)
    rules_layout.addLayout(first_row)
    rules_layout.addLayout(second_row)
    layout.addWidget(rules_group)
