from __future__ import annotations

try:
    from PySide6.QtWidgets import (
        QGridLayout,
        QHBoxLayout,
        QLabel,
        QPushButton,
        QTableWidget,
        QTabWidget,
        QVBoxLayout,
        QWidget,
    )
except ImportError:  # pragma: no cover
    QGridLayout = QHBoxLayout = QLabel = QPushButton = QTableWidget = QTabWidget = QVBoxLayout = QWidget = None

from app.page_tasks import run_tool_background
from app.pages.analysis_widgets import add_cards, counts_to_rows, populate_table
from app.widgets.report_viewer import ReportViewer
from app.widgets.tool_run_panel import ToolRunPanel
from core.issue_analysis import analyze_issues, generate_issue_analysis_report
from core.openers import open_path
from core.paths import resolve_project_paths


class IssueAnalysisPage(QWidget):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        layout = QVBoxLayout(self)
        heading = QLabel("Issue Analysis")
        heading.setStyleSheet("font-size: 18pt; font-weight: 600;")
        layout.addWidget(heading)
        buttons = QHBoxLayout()
        for label, callback in [
            ("Run Issue Analysis", self.run_report),
            ("Open Issue Analysis Reports Folder", self.open_reports),
            ("Refresh", self.refresh),
        ]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            buttons.addWidget(button)
        layout.addLayout(buttons)
        grid = QGridLayout()
        self.cards = add_cards(grid, ["Issues Logged", "Open Issues", "High Priority", "Missing Risk Data"])
        layout.addLayout(grid)
        tabs = QTabWidget()
        self.category_table = QTableWidget()
        self.cells_table = QTableWidget()
        self.missing_table = QTableWidget()
        self.fmea_table = QTableWidget()
        for label, table in [
            ("Issues by Category", self.category_table),
            ("Top Problem Cells", self.cells_table),
            ("Missing Risk Data", self.missing_table),
            ("Suggested FMEA Candidates", self.fmea_table),
        ]:
            tab = QWidget()
            box = QVBoxLayout(tab)
            box.addWidget(table)
            tabs.addTab(tab, label)
        layout.addWidget(tabs, stretch=2)
        self.preview = ReportViewer()
        self.preview.setMaximumHeight(230)
        layout.addWidget(self.preview)
        self.result_panel = ToolRunPanel()
        layout.addWidget(self.result_panel, stretch=1)
        self.refresh()

    def refresh(self) -> None:
        summary, error = analyze_issues(self.config.project_root)
        if error:
            self.result_panel.show_result(error)
            return
        assert summary is not None
        self.cards["Issues Logged"].set_value(str(summary.metrics.get("issues_logged", 0)))
        self.cards["Open Issues"].set_value(str(summary.metrics.get("open_issues", 0)))
        self.cards["High Priority"].set_value(str(summary.metrics.get("high_priority_count", 0)))
        self.cards["Missing Risk Data"].set_value(str(summary.metrics.get("missing_risk_count", 0)))
        populate_table(
            self.category_table, counts_to_rows(summary.category_counts, "Issue Category"), ["Issue Category", "Count"]
        )
        populate_table(
            self.cells_table, counts_to_rows(summary.press_counts, "Press/Machine #"), ["Press/Machine #", "Count"]
        )
        populate_table(
            self.missing_table,
            summary.missing_risk_rows,
            ["Issue ID", "Press/Machine #", "Issue Category", "Missing Fields"],
        )
        populate_table(
            self.fmea_table, summary.suggested_fmea, ["Issue Category", "Issue Count", "Suggested Failure Mode"]
        )
        self.preview.show_markdown_text(summary.to_markdown())

    def run_report(self) -> None:
        run_tool_background(
            self.result_panel,
            "issue_analysis_report",
            "Issue Analysis Report",
            lambda: generate_issue_analysis_report(self.config.project_root),
            self._report_finished,
            modifies_files=True,
        )

    def _report_finished(self, result) -> None:
        if result.output_reports:
            self.preview.load_report_file(result.output_reports[0])

    def open_reports(self) -> None:
        result = open_path(resolve_project_paths(self.config.project_root).issue_analysis_reports)
        if not result.success:
            self.result_panel.show_result(result)
