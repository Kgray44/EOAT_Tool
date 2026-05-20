from __future__ import annotations

try:
    from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget, QVBoxLayout, QWidget
except ImportError:  # pragma: no cover
    QGridLayout = QHBoxLayout = QLabel = QPushButton = QTableWidget = QVBoxLayout = QWidget = None

from app.pages.analysis_widgets import add_cards, populate_table
from app.page_tasks import run_tool_background
from app.widgets.report_viewer import ReportViewer
from app.widgets.tool_run_panel import ToolRunPanel
from core.fmea_analysis import analyze_fmea, generate_fmea_report
from core.openers import open_path
from core.paths import resolve_project_paths


class FmeaPage(QWidget):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        layout = QVBoxLayout(self)
        heading = QLabel("FMEA-Lite")
        heading.setStyleSheet("font-size: 18pt; font-weight: 600;")
        layout.addWidget(heading)
        buttons = QHBoxLayout()
        workflow = QLabel("Workflow: 1. Run analysis  ->  2. Review suggestions  ->  3. Check RPN  ->  4. Export/open report")
        workflow.setStyleSheet("color: #627d98;")
        layout.addWidget(workflow)
        for label, callback in [("Run FMEA Analysis", self.run_report), ("Calculate RPN / Refresh", self.refresh), ("Suggest FMEA Entries", self.refresh), ("Open FMEA Reports Folder", self.open_reports)]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            buttons.addWidget(button)
        apply_button = QPushButton("Apply Selected Suggestions - Coming Soon")
        apply_button.setToolTip("Workbook write-back for selected suggestions is intentionally planned for a later safe-apply workflow.")
        apply_button.setEnabled(False)
        buttons.addWidget(apply_button)
        layout.addLayout(buttons)
        grid = QGridLayout()
        self.cards = add_cards(grid, ["Existing Rows", "Suggested Entries", "Missing Risk Rows", "Top RPN"])
        layout.addLayout(grid)
        tables = QHBoxLayout()
        self.risk_table = QTableWidget()
        self.suggest_table = QTableWidget()
        for label, table in [("Top Risks", self.risk_table), ("Suggested FMEA Entries", self.suggest_table)]:
            box = QVBoxLayout()
            box.addWidget(QLabel(label))
            box.addWidget(table)
            tables.addLayout(box)
        layout.addLayout(tables, stretch=1)
        self.preview = ReportViewer()
        self.preview.setMaximumHeight(230)
        layout.addWidget(self.preview)
        self.result_panel = ToolRunPanel()
        layout.addWidget(self.result_panel, stretch=1)
        self.refresh()

    def refresh(self) -> None:
        summary, error = analyze_fmea(self.config.project_root)
        if error:
            self.result_panel.show_result(error)
            return
        assert summary is not None
        self.cards["Existing Rows"].set_value(str(summary.metrics.get("existing_fmea_rows", 0)))
        self.cards["Suggested Entries"].set_value(str(summary.metrics.get("suggested_entries", 0)))
        self.cards["Missing Risk Rows"].set_value(str(summary.metrics.get("missing_risk_rows", 0)))
        self.cards["Top RPN"].set_value(str(summary.metrics.get("top_rpn", 0)))
        populate_table(self.risk_table, summary.ranked_rows[:10], ["FMEA ID", "Press/Machine #", "Failure Mode", "RPN", "Recommended Action"])
        populate_table(self.suggest_table, summary.suggestions, ["Failure Mode", "Issue Category", "Issue Count", "Recommended Action"])
        self.preview.show_markdown_text(summary.to_markdown())

    def run_report(self) -> None:
        run_tool_background(
            self.result_panel,
            "fmea_report",
            "FMEA-Lite Analysis",
            lambda: generate_fmea_report(self.config.project_root),
            self._report_finished,
            modifies_files=True,
        )

    def _report_finished(self, result) -> None:
        if result.output_reports:
            self.preview.load_report_file(result.output_reports[0])

    def open_reports(self) -> None:
        result = open_path(resolve_project_paths(self.config.project_root).fmea_reports)
        if not result.success:
            self.result_panel.show_result(result)
