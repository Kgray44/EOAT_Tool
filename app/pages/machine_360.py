from __future__ import annotations

try:
    from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPushButton, QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget
except ImportError:  # pragma: no cover
    QHBoxLayout = QLabel = QLineEdit = QPushButton = QTableWidget = QTableWidgetItem = QTextEdit = QVBoxLayout = QWidget = None

from core.project_data_service import Machine360Context, build_machine_360_context


class Machine360Page(QWidget):
    SUMMARY_COLUMNS = ["Metric", "Value"]
    AUDIT_COLUMNS = ["Audit ID", "Entry Type", "Tool #", "EOAT Type", "Status", "Priority"]

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.context: Machine360Context | None = None

        layout = QVBoxLayout(self)
        heading = QLabel("Machine 360")
        heading.setStyleSheet("font-size: 18pt; font-weight: 600;")
        layout.addWidget(heading)

        controls = QHBoxLayout()
        self.machine_edit = QLineEdit()
        self.machine_edit.setPlaceholderText("Press/Machine #")
        self.machine_edit.returnPressed.connect(self.refresh)
        refresh_button = QPushButton("Refresh")
        refresh_button.clicked.connect(self.refresh)
        controls.addWidget(QLabel("Machine"))
        controls.addWidget(self.machine_edit)
        controls.addWidget(refresh_button)
        controls.addStretch(1)
        layout.addLayout(controls)

        self.summary_table = QTableWidget(0, len(self.SUMMARY_COLUMNS))
        self.summary_table.setHorizontalHeaderLabels(self.SUMMARY_COLUMNS)
        layout.addWidget(self.summary_table)

        self.audit_table = QTableWidget(0, len(self.AUDIT_COLUMNS))
        self.audit_table.setHorizontalHeaderLabels(self.AUDIT_COLUMNS)
        layout.addWidget(self.audit_table, stretch=1)

        self.detail_text = QTextEdit()
        self.detail_text.setReadOnly(True)
        self.detail_text.setMinimumHeight(180)
        layout.addWidget(self.detail_text, stretch=1)

    def refresh(self, *_args) -> None:
        machine = self.machine_edit.text().strip()
        self.context = build_machine_360_context(self.config.project_root, machine)
        self._populate_context(self.context)

    def refresh_data(self) -> None:
        self.refresh()

    def select_machine(self, machine: str) -> bool:
        self.machine_edit.setText(str(machine or "").strip())
        self.refresh()
        return bool(self.context and self.context.machine_number)

    def on_project_root_changed(self, config) -> None:
        self.config = config
        self.refresh()

    def _populate_context(self, context: Machine360Context) -> None:
        metrics = [
            ("Machine", context.display_name),
            ("Physical audits", context.metrics.get("physical_audit_count", 0)),
            ("Compatible entries", context.metrics.get("compatible_entry_count", 0)),
            ("Linked compatible", context.metrics.get("linked_compatible_count", 0)),
            ("Open items", context.metrics.get("open_item_count", 0)),
            ("Missing required photo evidence", context.metrics.get("missing_required_photo_evidence", 0)),
            ("Guided audit gaps", context.metrics.get("guided_gap_count", 0)),
        ]
        self.summary_table.setRowCount(len(metrics))
        for row, (label, value) in enumerate(metrics):
            self.summary_table.setItem(row, 0, QTableWidgetItem(str(label)))
            self.summary_table.setItem(row, 1, QTableWidgetItem(str(value)))
        rows = [*context.physical_audits, *context.compatible_entries]
        self.audit_table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            values = [
                row.get("Audit ID", ""),
                row.get("Entry Type", "Audited"),
                row.get("Tool #", ""),
                row.get("EOAT Type", ""),
                row.get("Status", ""),
                row.get("Priority", ""),
            ]
            for col, value in enumerate(values):
                self.audit_table.setItem(row_index, col, QTableWidgetItem(str(value or "")))
        self.detail_text.setPlainText(self._details_text(context))

    def _details_text(self, context: Machine360Context) -> str:
        lines = [context.display_name, ""]
        if context.warnings:
            lines.append("Warnings:")
            lines.extend(f"- {warning}" for warning in context.warnings)
            lines.append("")
        lines.append("Recommended Actions:")
        lines.extend(f"- {action}" for action in context.recommended_actions)
        lines.append("")
        lines.append("Open Items:")
        if context.open_items:
            lines.extend(f"- {item['severity']}: {item['title']} ({item['status']})" for item in context.open_items[:10])
        else:
            lines.append("- None")
        lines.append("")
        lines.append("Guided Audit:")
        if context.guided_plans:
            for plan in context.guided_plans[:3]:
                lines.append(f"- {plan.get('audit_id')}: {plan.get('summary')}")
        else:
            lines.append("- No physical audit plan available.")
        return "\n".join(lines)

