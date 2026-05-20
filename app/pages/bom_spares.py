from __future__ import annotations

try:
    from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QPushButton, QSplitter, QTableWidget, QVBoxLayout, QWidget
except ImportError:  # pragma: no cover
    QGridLayout = QHBoxLayout = QLabel = QPushButton = QSplitter = QTableWidget = QVBoxLayout = QWidget = None

from app.widgets.report_viewer import ReportViewer
from app.widgets.tool_run_panel import ToolRunPanel
from app.page_tasks import run_tool_background
from core.bom_standardization import analyze_bom_standardization, generate_bom_standardization_report
from core.openers import open_path
from core.paths import resolve_project_paths
from .analysis_widgets import add_cards, counts_to_rows, populate_table


class BomSparesPage(QWidget):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        layout = QVBoxLayout(self)
        heading = QLabel("BOM & Spare Parts")
        heading.setStyleSheet("font-size: 18pt; font-weight: 600;")
        layout.addWidget(heading)

        buttons = QHBoxLayout()
        for label, callback in [
            ("Run BOM/Spare Parts Analysis", self.run_report),
            ("Open Reports Folder", self.open_folder),
            ("Refresh Preview Data", self.refresh_data),
        ]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            buttons.addWidget(button)
        layout.addLayout(buttons)

        card_layout = QGridLayout()
        self.cards = add_cards(card_layout, ["EOATs Scanned", "Missing Data Rows", "Opportunities"])
        layout.addLayout(card_layout)

        splitter = QSplitter()
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(QLabel("Common Parts / Components"))
        self.common_table = QTableWidget()
        left_layout.addWidget(self.common_table)
        left_layout.addWidget(QLabel("Missing BOM/Spare Data"))
        self.missing_table = QTableWidget()
        left_layout.addWidget(self.missing_table)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        self.result_panel = ToolRunPanel()
        right_layout.addWidget(self.result_panel)
        self.preview = ReportViewer()
        right_layout.addWidget(self.preview)
        splitter.addWidget(right)
        splitter.setSizes([560, 560])
        layout.addWidget(splitter, stretch=1)
        self.refresh_data()

    def refresh_data(self) -> None:
        data, warnings, _details = analyze_bom_standardization(self.config.project_root)
        self.cards["EOATs Scanned"].set_value(str(len(data["rows"])))
        self.cards["Missing Data Rows"].set_value(str(len(data["missing_rows"])))
        self.cards["Opportunities"].set_value(str(len(data["opportunities"])))
        common_rows = []
        for label, counts in data["counts"].items():
            for row in counts_to_rows(counts, "Value"):
                row["Category"] = label
                common_rows.append(row)
        populate_table(self.common_table, common_rows, ["Category", "Value", "Count"])
        populate_table(self.missing_table, data["missing_rows"][:25], ["Audit ID", "Press/Machine #", "EOAT Type", "Missing Field Count", "Missing Fields"])
        if warnings:
            self.result_panel.show_text("\n".join(warnings))

    def run_report(self) -> None:
        run_tool_background(
            self.result_panel,
            "bom_standardization_report",
            "BOM/Spare Parts Analysis",
            lambda: generate_bom_standardization_report(self.config.project_root),
            self._report_finished,
            modifies_files=True,
        )

    def _report_finished(self, result) -> None:
        if result.output_reports:
            self.preview.load_report_file(result.output_reports[0])
        self.refresh_data()

    def open_folder(self) -> None:
        result = open_path(resolve_project_paths(self.config.project_root).bom_standardization_reports)
        if not result.success:
            self.result_panel.show_result(result)
