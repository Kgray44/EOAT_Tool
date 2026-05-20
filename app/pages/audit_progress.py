from __future__ import annotations

try:
    from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget
except ImportError:  # pragma: no cover
    QGridLayout = QHBoxLayout = QLabel = QPushButton = QTableWidget = QTableWidgetItem = QVBoxLayout = QWidget = None

from app.widgets.report_viewer import ReportViewer
from app.widgets.status_card import StatusCard
from app.widgets.tool_run_panel import ToolRunPanel
from app.page_tasks import run_tool_background
from core.audit_progress import calculate_audit_progress, generate_audit_progress_report
from core.openers import open_path
from core.paths import resolve_project_paths


class AuditProgressPage(QWidget):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.cards: dict[str, StatusCard] = {}
        layout = QVBoxLayout(self)
        heading = QLabel("Audit Progress")
        heading.setStyleSheet("font-size: 18pt; font-weight: 600;")
        layout.addWidget(heading)

        buttons = QHBoxLayout()
        for label, callback in [
            ("Refresh Metrics", self.refresh_metrics),
            ("Generate Progress Report", self.generate_report),
            ("Open Progress Reports Folder", self.open_reports),
        ]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            buttons.addWidget(button)
        layout.addLayout(buttons)

        grid = QGridLayout()
        for index, key in enumerate(["EOATs Audited", "Photos Indexed", "Interviews Logged", "Issues Logged", "Pilot Candidates", "Open Actions"]):
            card = StatusCard(key, "Not checked")
            self.cards[key] = card
            grid.addWidget(card, index // 3, index % 3)
        layout.addLayout(grid)

        tables = QHBoxLayout()
        self.counts_table = QTableWidget()
        self.counts_table.setColumnCount(2)
        self.counts_table.setHorizontalHeaderLabels(["Metric", "Count"])
        tables.addWidget(self.counts_table)
        self.missing_table = QTableWidget()
        self.missing_table.setColumnCount(2)
        self.missing_table.setHorizontalHeaderLabels(["Missing Field", "Count"])
        tables.addWidget(self.missing_table)
        layout.addLayout(tables, stretch=1)

        self.preview = ReportViewer()
        layout.addWidget(self.preview, stretch=1)
        self.result_panel = ToolRunPanel()
        layout.addWidget(self.result_panel, stretch=1)
        self.refresh_metrics()

    def refresh_metrics(self) -> None:
        summary, error = calculate_audit_progress(self.config.project_root)
        if error:
            self.result_panel.show_result(error)
            return
        assert summary is not None
        metrics = summary.metrics
        self.cards["EOATs Audited"].set_value(str(metrics.get("audited_eoat_count", 0)))
        self.cards["Photos Indexed"].set_value(str(metrics.get("photos_indexed_count", 0)))
        self.cards["Interviews Logged"].set_value(str(metrics.get("interviews_logged_count", 0)))
        self.cards["Issues Logged"].set_value(str(metrics.get("issues_logged_count", 0)))
        self.cards["Pilot Candidates"].set_value(
            f"Yes: {metrics.get('pilot_candidate_yes_count', 0)}, Maybe: {metrics.get('pilot_candidate_maybe_count', 0)}"
        )
        self.cards["Open Actions"].set_value(str(metrics.get("open_action_items_count", 0)))

        rows = list(metrics.items())
        self.counts_table.setRowCount(len(rows))
        for row, (key, value) in enumerate(rows):
            self.counts_table.setItem(row, 0, QTableWidgetItem(str(key)))
            self.counts_table.setItem(row, 1, QTableWidgetItem(str(value)))
        missing_rows = list(summary.missing_field_counts.items())
        self.missing_table.setRowCount(len(missing_rows))
        for row, (key, value) in enumerate(missing_rows):
            self.missing_table.setItem(row, 0, QTableWidgetItem(str(key)))
            self.missing_table.setItem(row, 1, QTableWidgetItem(str(value)))
        self.counts_table.resizeColumnsToContents()
        self.missing_table.resizeColumnsToContents()
        self.preview.show_markdown_text(summary.to_markdown())

    def generate_report(self) -> None:
        run_tool_background(
            self.result_panel,
            "audit_progress_report",
            "Audit Progress Report",
            lambda: generate_audit_progress_report(self.config.project_root),
            self._report_finished,
            modifies_files=True,
        )

    def _report_finished(self, result) -> None:
        if result.output_reports:
            self.preview.load_report_file(result.output_reports[0])
        self.refresh_metrics()

    def open_reports(self) -> None:
        result = open_path(resolve_project_paths(self.config.project_root).audit_progress_reports)
        if not result.success:
            self.result_panel.show_result(result)
