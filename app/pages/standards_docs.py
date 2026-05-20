from __future__ import annotations

try:
    from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget, QVBoxLayout, QWidget
except ImportError:  # pragma: no cover
    QGridLayout = QHBoxLayout = QLabel = QPushButton = QTableWidget = QVBoxLayout = QWidget = None

from app.pages.analysis_widgets import add_cards, counts_to_rows, populate_table
from app.page_tasks import run_tool_background
from app.widgets.report_viewer import ReportViewer
from app.widgets.tool_run_panel import ToolRunPanel
from core.documentation_gaps import generate_documentation_gap_report, scan_documentation_gaps
from core.openers import open_path
from core.paths import resolve_project_paths


class StandardsDocsPage(QWidget):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        layout = QVBoxLayout(self)
        heading = QLabel("Standards & Documentation")
        heading.setStyleSheet("font-size: 18pt; font-weight: 600;")
        layout.addWidget(heading)
        buttons = QHBoxLayout()
        for label, callback in [("Run Documentation Gap Scan", self.run_report), ("Open Documentation Gap Reports Folder", self.open_reports), ("Refresh", self.refresh)]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            buttons.addWidget(button)
        layout.addLayout(buttons)
        grid = QGridLayout()
        self.cards = add_cards(grid, ["EOATs Scanned", "Total Gaps", "Critical Gaps", "Important Gaps"])
        layout.addLayout(grid)
        tables = QHBoxLayout()
        self.top_table = QTableWidget()
        self.missing_table = QTableWidget()
        for label, table in [("Top EOATs by Gap Count", self.top_table), ("Top Missing Fields", self.missing_table)]:
            box = QVBoxLayout()
            box.addWidget(QLabel(label))
            box.addWidget(table)
            tables.addLayout(box)
        layout.addLayout(tables, stretch=1)
        self.preview = ReportViewer()
        layout.addWidget(self.preview, stretch=1)
        self.result_panel = ToolRunPanel()
        layout.addWidget(self.result_panel, stretch=1)
        self.refresh()

    def refresh(self) -> None:
        summary, error = scan_documentation_gaps(self.config.project_root)
        if error:
            self.result_panel.show_result(error)
            return
        assert summary is not None
        self.cards["EOATs Scanned"].set_value(str(summary.metrics.get("eoats_scanned", 0)))
        self.cards["Total Gaps"].set_value(str(summary.metrics.get("total_gaps", 0)))
        self.cards["Critical Gaps"].set_value(str(summary.metrics.get("critical_gaps", 0)))
        self.cards["Important Gaps"].set_value(str(summary.metrics.get("important_gaps", 0)))
        populate_table(self.top_table, summary.top_eoats, ["Audit ID", "Press/Machine #", "Gap Count", "Critical", "Important", "Nice-to-have"])
        populate_table(self.missing_table, counts_to_rows(summary.missing_field_counts, "Missing Field"), ["Missing Field", "Count"])
        self.preview.show_markdown_text(summary.to_markdown())

    def run_report(self) -> None:
        run_tool_background(
            self.result_panel,
            "documentation_gap_report",
            "Documentation Gap Scan",
            lambda: generate_documentation_gap_report(self.config.project_root),
            self._report_finished,
            modifies_files=True,
        )

    def _report_finished(self, result) -> None:
        if result.output_reports:
            self.preview.load_report_file(result.output_reports[0])

    def open_reports(self) -> None:
        result = open_path(resolve_project_paths(self.config.project_root).documentation_gap_reports)
        if not result.success:
            self.result_panel.show_result(result)
