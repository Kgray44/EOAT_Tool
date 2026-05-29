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
from core.app_health import run_app_health_checks


class AppHealthPage(QWidget):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        layout = QVBoxLayout(self)
        heading = QLabel("App Health Doctor")
        heading.setStyleSheet("font-size: 18pt; font-weight: 600;")
        layout.addWidget(heading)

        controls = QHBoxLayout()
        self.scheduled_check = QCheckBox("Check scheduled tasks")
        self.repo_check = QCheckBox("Run repo safety audit")
        refresh = QPushButton("Run Health Check")
        refresh.clicked.connect(self.refresh)
        controls.addWidget(self.scheduled_check)
        controls.addWidget(self.repo_check)
        controls.addWidget(refresh)
        controls.addStretch(1)
        layout.addLayout(controls)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Check", "Status", "Severity", "Details", "Recommendation", "Key"])
        layout.addWidget(self.table, stretch=2)
        self.result_panel = ToolRunPanel()
        layout.addWidget(self.result_panel, stretch=1)
        self.refresh()

    def refresh(self) -> None:
        summary = run_app_health_checks(
            self.config.project_root,
            config=self.config,
            check_repo_safety=self.repo_check.isChecked(),
            check_scheduled_tasks=self.scheduled_check.isChecked(),
        )
        self.table.setRowCount(len(summary.checks))
        for row, check in enumerate(summary.checks):
            for col, value in enumerate([check.label, check.status, check.severity, check.details, check.recommendation, check.key]):
                self.table.setItem(row, col, QTableWidgetItem(str(value)))
        self.table.resizeColumnsToContents()
        self.result_panel.show_text(f"App health status: {summary.status}. Counts: {summary.counts}")
