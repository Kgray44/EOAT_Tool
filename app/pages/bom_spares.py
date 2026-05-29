from __future__ import annotations

try:
    from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QPushButton, QSplitter, QTableWidget, QVBoxLayout, QWidget
except ImportError:  # pragma: no cover
    QGridLayout = QHBoxLayout = QLabel = QPushButton = QSplitter = QTableWidget = QVBoxLayout = QWidget = None

from app.widgets.report_viewer import ReportViewer
from app.widgets.tool_run_panel import ToolRunPanel
from app.page_tasks import run_tool_background
from core.openers import open_path
from core.paths import resolve_project_paths
from core.standardization import analyze_standardization_opportunities, generate_standardization_report
from .analysis_widgets import add_cards, populate_table


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
        self.cards = add_cards(card_layout, ["EOATs Scanned", "Components", "Recommendations", "Cleanup Actions"])
        layout.addLayout(card_layout)

        splitter = QSplitter()
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(QLabel("Component Frequency"))
        self.frequency_table = QTableWidget()
        self.common_table = self.frequency_table
        left_layout.addWidget(self.frequency_table)
        left_layout.addWidget(QLabel("Unknown / Missing Part Numbers"))
        self.unknown_table = QTableWidget()
        self.missing_table = self.unknown_table
        left_layout.addWidget(self.unknown_table)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.addWidget(QLabel("Recommended Standard Parts"))
        self.recommendations_table = QTableWidget()
        right_layout.addWidget(self.recommendations_table)
        right_layout.addWidget(QLabel("Candidate BOM Cleanup Actions"))
        self.cleanup_table = QTableWidget()
        right_layout.addWidget(self.cleanup_table)
        self.result_panel = ToolRunPanel()
        right_layout.addWidget(self.result_panel)
        self.preview = ReportViewer()
        right_layout.addWidget(self.preview)
        splitter.addWidget(right)
        splitter.setSizes([560, 560])
        layout.addWidget(splitter, stretch=1)
        self.refresh_data()

    def refresh_data(self) -> None:
        analysis = analyze_standardization_opportunities(self.config.project_root)
        self.cards["EOATs Scanned"].set_value(str(len(analysis.rows)))
        self.cards["Components"].set_value(str(len(analysis.observations)))
        self.cards["Recommendations"].set_value(str(len(analysis.recommended_standard_parts_list)))
        self.cards["Cleanup Actions"].set_value(str(len(analysis.candidate_bom_cleanup_actions)))
        populate_table(
            self.frequency_table,
            analysis.component_frequency_table[:75],
            ["Category", "Component", "Count", "Machines", "Audits", "Raw Values"],
        )
        populate_table(
            self.unknown_table,
            analysis.unknown_missing_part_number_table[:50],
            ["Audit ID", "Press/Machine #", "EOAT Type", "Field", "Current Value", "Reason"],
        )
        populate_table(
            self.recommendations_table,
            analysis.recommended_standard_parts_list[:50],
            ["Category", "Recommended Part", "Count", "Machines", "Audits", "Reason"],
        )
        populate_table(
            self.cleanup_table,
            analysis.candidate_bom_cleanup_actions[:75],
            ["Action Type", "Audit ID", "Press/Machine #", "Field", "Current Value", "Recommended Value", "Reason"],
        )
        if analysis.warnings:
            self.result_panel.show_text("\n".join(analysis.warnings))

    def run_report(self) -> None:
        run_tool_background(
            self.result_panel,
            "bom_standardization_report",
            "BOM/Spare Parts Analysis",
            lambda: generate_standardization_report(self.config.project_root),
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
