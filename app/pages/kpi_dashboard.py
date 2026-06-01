from __future__ import annotations

try:
    from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget, QVBoxLayout, QWidget
except ImportError:  # pragma: no cover
    QGridLayout = QHBoxLayout = QLabel = QPushButton = QTableWidget = QVBoxLayout = QWidget = None

from app.page_tasks import run_tool_background
from app.pages.analysis_widgets import add_cards, counts_to_rows, populate_table
from app.widgets.report_viewer import ReportViewer
from app.widgets.tool_run_panel import ToolRunPanel
from core.kpi_analysis import analyze_kpis, generate_kpi_dashboard_report
from core.openers import open_path
from core.paths import resolve_project_paths


class KpiDashboardPage(QWidget):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        layout = QVBoxLayout(self)
        heading = QLabel("KPI Dashboard")
        heading.setStyleSheet("font-size: 18pt; font-weight: 600;")
        layout.addWidget(heading)
        buttons = QHBoxLayout()
        for label, callback in [
            ("Run KPI Analysis", self.run_report),
            ("Open KPI Dashboard Exports Folder", self.open_reports),
            ("Refresh", self.refresh),
        ]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            buttons.addWidget(button)
        layout.addLayout(buttons)
        grid = QGridLayout()
        self.cards = add_cards(
            grid, ["KPI Rows", "Downtime Minutes", "Part Drops", "Mis-Picks", "Scrap Qty", "Missing KPI Data"]
        )
        layout.addLayout(grid)
        tables = QHBoxLayout()
        self.by_press_table = QTableWidget()
        self.missing_table = QTableWidget()
        for label, table in [("KPI by Press/Machine #", self.by_press_table), ("Missing KPI Data", self.missing_table)]:
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
        summary, error = analyze_kpis(self.config.project_root)
        if error:
            self.result_panel.show_result(error)
            return
        assert summary is not None
        metrics = summary.metrics
        self.cards["KPI Rows"].set_value(str(metrics.get("kpi_rows", 0)))
        self.cards["Downtime Minutes"].set_value(str(metrics.get("total_downtime_minutes", 0)))
        self.cards["Part Drops"].set_value(str(metrics.get("part_drops", 0)))
        self.cards["Mis-Picks"].set_value(str(metrics.get("mis_picks", 0)))
        self.cards["Scrap Qty"].set_value(str(metrics.get("scrap_quantity", 0)))
        self.cards["Missing KPI Data"].set_value(str(metrics.get("missing_kpi_fields_total", 0)))
        self._apply_card_truth(summary)
        populate_table(
            self.by_press_table,
            summary.by_press,
            [
                "Press/Machine #",
                "Downtime Minutes",
                "Part Drops",
                "Mis-Picks",
                "Scrap Quantity",
                "Maintenance Events",
                "Source Type",
                "Date Range",
                "Record Count",
                "Confidence",
                "Missing Data Warning",
            ],
        )
        populate_table(self.missing_table, counts_to_rows(summary.missing_fields, "Field"), ["Field", "Count"])
        self.preview.show_markdown_text(summary.to_markdown())

    def _apply_card_truth(self, summary) -> None:
        metric_by_card = {
            "KPI Rows": None,
            "Downtime Minutes": "Downtime Minutes",
            "Part Drops": "Part Drops",
            "Mis-Picks": "Mis-Picks",
            "Scrap Qty": "Scrap Quantity",
            "Missing KPI Data": None,
        }
        for card_name, metric in metric_by_card.items():
            card = self.cards.get(card_name)
            if card is None or not hasattr(card, "set_detail"):
                continue
            if metric:
                label = summary.card_truth(metric)
                card.set_detail(
                    label.card_detail()
                    if label
                    else "Source: missing data\nRange: No dated records\nRecords: 0/0\nConfidence: Missing\nMissing: No KPI label available."
                )
            else:
                card.set_detail(
                    "\n".join(
                        [
                            "Source: KPI Baseline workbook",
                            f"Range: {summary.metrics.get('date_range', 'No dated records')}",
                            f"Records: {summary.metrics.get('kpi_rows', 0)}",
                            f"Confidence: {summary.metrics.get('overall_confidence', 'Missing')}",
                            f"Missing: {summary.metrics.get('missing_kpi_fields_total', 0)} required KPI field gap(s)",
                        ]
                    )
                )

    def run_report(self) -> None:
        run_tool_background(
            self.result_panel,
            "kpi_dashboard_report",
            "KPI Dashboard Report",
            lambda: generate_kpi_dashboard_report(self.config.project_root),
            self._report_finished,
            modifies_files=True,
        )

    def _report_finished(self, result) -> None:
        if result.output_reports:
            self.preview.load_report_file(result.output_reports[0])

    def open_reports(self) -> None:
        result = open_path(resolve_project_paths(self.config.project_root).kpi_dashboard_exports)
        if not result.success:
            self.result_panel.show_result(result)
