from __future__ import annotations

try:
    from PySide6.QtWidgets import (
        QCheckBox,
        QHBoxLayout,
        QLabel,
        QPushButton,
        QTableWidget,
        QTableWidgetItem,
        QVBoxLayout,
        QWidget,
    )
except ImportError:  # pragma: no cover
    QCheckBox = QHBoxLayout = QLabel = QPushButton = QTableWidget = QTableWidgetItem = QVBoxLayout = QWidget = None

from app.widgets.tool_run_panel import ToolRunPanel
from core.openers import open_path
from core.paths import resolve_project_paths
from core.qr_labels import build_qr_labels, export_qr_label_sheet


class QrLabelsPage(QWidget):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        layout = QVBoxLayout(self)
        heading = QLabel("QR Labels")
        heading.setStyleSheet("font-size: 18pt; font-weight: 600;")
        layout.addWidget(heading)

        controls = QHBoxLayout()
        self.machine_check = QCheckBox("Machine labels")
        self.machine_check.setChecked(True)
        self.audit_check = QCheckBox("Audit labels")
        self.audit_check.setChecked(True)
        controls.addWidget(self.machine_check)
        controls.addWidget(self.audit_check)
        for label, callback in [
            ("Preview Values", self.refresh),
            ("Export Label Sheet", self.export),
            ("Open QR Folder", self.open_folder),
        ]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            controls.addWidget(button)
        layout.addLayout(controls)

        self.table = QTableWidget()
        layout.addWidget(self.table, stretch=2)
        self.result_panel = ToolRunPanel()
        layout.addWidget(self.result_panel, stretch=1)
        self.refresh()

    def refresh(self) -> None:
        labels = build_qr_labels(
            self.config.project_root,
            include_machines=self.machine_check.isChecked(),
            include_audits=self.audit_check.isChecked(),
        )
        columns = ["label_type", "target_id", "display_label", "qr_value"]
        self.table.setColumnCount(len(columns))
        self.table.setHorizontalHeaderLabels(["Type", "Target", "Label", "QR Value"])
        self.table.setRowCount(len(labels))
        for row_index, label in enumerate(labels):
            data = label.to_dict()
            for col_index, column in enumerate(columns):
                self.table.setItem(row_index, col_index, QTableWidgetItem(str(data.get(column, ""))))
        self.table.resizeColumnsToContents()
        self.result_panel.show_text(f"Previewed {len(labels)} minimal QR value(s).")

    def export(self) -> None:
        result = export_qr_label_sheet(
            self.config.project_root,
            include_machines=self.machine_check.isChecked(),
            include_audits=self.audit_check.isChecked(),
        )
        self.result_panel.show_result(result)

    def open_folder(self) -> None:
        result = open_path(resolve_project_paths(self.config.project_root).qr_labels)
        if not result.success:
            self.result_panel.show_result(result)
