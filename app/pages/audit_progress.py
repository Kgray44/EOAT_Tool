from __future__ import annotations

try:
    from PySide6.QtWidgets import (
        QGridLayout,
        QHBoxLayout,
        QLabel,
        QPushButton,
        QTableWidget,
        QTableWidgetItem,
        QTabWidget,
        QVBoxLayout,
        QWidget,
    )
except ImportError:  # pragma: no cover
    QGridLayout = QHBoxLayout = QLabel = QPushButton = QTableWidget = QTableWidgetItem = QTabWidget = QVBoxLayout = (
        QWidget
    ) = None

from app.page_tasks import run_tool_background
from app.widgets.report_viewer import ReportViewer
from app.widgets.status_card import StatusCard
from app.widgets.tool_run_panel import ToolRunPanel
from core.audit_progress import calculate_audit_progress, generate_audit_progress_report
from core.eoat_ids import assign_missing_eoat_assembly_ids_in_workbook
from core.openers import open_path
from core.paths import resolve_project_paths


class AuditProgressPage(QWidget):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.cards: dict[str, StatusCard] = {}
        layout = QVBoxLayout(self)
        heading = QLabel("EOAT Documentation Progress")
        heading.setStyleSheet("font-size: 18pt; font-weight: 600;")
        layout.addWidget(heading)

        buttons = QHBoxLayout()
        for label, callback in [
            ("Refresh Metrics", self.refresh_metrics),
            ("Assign Missing EOAT IDs", self.assign_missing_eoat_ids),
            ("Generate Progress Report", self.generate_report),
            ("Open Progress Reports Folder", self.open_reports),
        ]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            buttons.addWidget(button)
        layout.addLayout(buttons)

        grid = QGridLayout()
        for index, key in enumerate(
            [
                "EOAT Documentation Rows",
                "Bench Audit Rows",
                "Audited Required Relationships",
                "Compatible Relationships",
                "Total Covered Relationships",
                "Remaining Relationships",
                "Compatibility Opportunities",
                "Open Actions",
                "Issues Logged",
                "Multi-Tool EOATs",
            ]
        ):
            card = StatusCard(key, "Not checked")
            self.cards[key] = card
            grid.addWidget(card, index // 3, index % 3)
        layout.addLayout(grid)

        tables = QTabWidget()
        self.counts_table = QTableWidget()
        self.counts_table.setColumnCount(2)
        self.counts_table.setHorizontalHeaderLabels(["Metric", "Count"])
        tables.addTab(self.counts_table, "Coverage Summary")
        self.missing_table = QTableWidget()
        tables.addTab(self.missing_table, "Missing Relationships")
        self.opportunities_table = QTableWidget()
        tables.addTab(self.opportunities_table, "Compatibility Opportunities")
        self.machine_table = QTableWidget()
        tables.addTab(self.machine_table, "Machine Coverage")
        self.multi_tool_table = QTableWidget()
        tables.addTab(self.multi_tool_table, "Multi-Tool EOATs")
        self.eoat_machine_table = QTableWidget()
        tables.addTab(self.eoat_machine_table, "EOAT Machine Compatibility")
        self.entry_type_table = QTableWidget()
        tables.addTab(self.entry_type_table, "Existing Entries by Type")
        self.audit_context_table = QTableWidget()
        tables.addTab(self.audit_context_table, "Entries by Audit Context")
        layout.addWidget(tables, stretch=1)

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
        self.cards["EOAT Documentation Rows"].set_value(str(metrics.get("physical_audit_rows", 0)))
        self.cards["Bench Audit Rows"].set_value(str(metrics.get("bench_audit_rows", 0)))
        self.cards["Audited Required Relationships"].set_value(str(metrics.get("physically_audited_relationships", 0)))
        self.cards["Compatible Relationships"].set_value(str(metrics.get("compatible_relationships", 0)))
        self.cards["Total Covered Relationships"].set_value(str(metrics.get("total_covered_relationships", 0)))
        self.cards["Remaining Relationships"].set_value(str(metrics.get("remaining_relationships", 0)))
        self.cards["Compatibility Opportunities"].set_value(
            str(metrics.get("compatibility_opportunities_available", 0))
        )
        self.cards["Open Actions"].set_value(str(metrics.get("open_action_items_count", 0)))
        self.cards["Issues Logged"].set_value(str(metrics.get("issues_logged_count", 0)))
        self.cards["Multi-Tool EOATs"].set_value(
            f"{metrics.get('multi_tool_eoat_count', 0)} shared / "
            f"{metrics.get('total_eoat_assembly_ids', 0)} IDs / "
            f"{metrics.get('total_eoat_tool_links', 0)} links"
        )

        self._fill_table(
            self.counts_table,
            ["Metric", "Count"],
            [{"Metric": label, "Count": value} for label, value in summary.coverage_summary],
        )
        self._fill_table(
            self.missing_table,
            ["Machine No.", "NGW Part Number", "NGW Part Description", "Reason Missing", "Suggested Next Action"],
            summary.missing_relationships,
        )
        self._fill_table(
            self.opportunities_table,
            [
                "NGW Part Number",
                "NGW Part Description",
                "Source Audited Machine",
                "Compatible Missing Machines",
                "Suggested Action",
            ],
            summary.compatibility_opportunities,
        )
        self._fill_table(
            self.machine_table,
            [
                "Machine No.",
                "Required Relationships",
                "Audited",
                "Compatible",
                "Covered Total",
                "Remaining",
                "Coverage %",
            ],
            summary.machine_coverage,
        )
        self._fill_table(
            self.multi_tool_table,
            [
                "EOAT Assembly ID",
                "Tool Count",
                "Tool #s",
                "Machine #s",
                "Audit Machine #s",
                "Press Capacity Machine #s",
                "Audit IDs",
            ],
            summary.multi_tool_eoats,
        )
        self._fill_table(
            self.eoat_machine_table,
            [
                "EOAT Assembly ID",
                "Tool #s",
                "Machine #s",
                "Audit Machine #s",
                "Press Capacity Machine #s",
                "Audit IDs",
            ],
            summary.eoat_machine_compatibility,
        )
        self._fill_table(
            self.entry_type_table,
            ["Entry Type", "Count"],
            [{"Entry Type": key, "Count": value} for key, value in summary.entry_type_counts.items()],
        )
        self._fill_table(
            self.audit_context_table,
            ["Audit Context", "Count"],
            [{"Audit Context": key, "Count": value} for key, value in summary.audit_context_counts.items()],
        )
        self.preview.show_markdown_text(summary.to_markdown())

    def _fill_table(self, table: QTableWidget, columns: list[str], rows: list[dict[str, object]]) -> None:
        table.setColumnCount(len(columns))
        table.setHorizontalHeaderLabels(columns)
        table.setRowCount(len(rows))
        for row_index, row_data in enumerate(rows):
            for col_index, column in enumerate(columns):
                table.setItem(row_index, col_index, QTableWidgetItem(str(row_data.get(column, ""))))
        table.resizeColumnsToContents()

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

    def assign_missing_eoat_ids(self) -> None:
        run_tool_background(
            self.result_panel,
            "assign_missing_eoat_ids",
            "Assign Missing EOAT IDs",
            lambda: assign_missing_eoat_assembly_ids_in_workbook(self.config.project_root),
            self._eoat_assignment_finished,
            modifies_files=True,
            workbook_lock=True,
        )

    def _eoat_assignment_finished(self, result) -> None:
        self.result_panel.show_result(result)
        self.refresh_metrics()

    def open_reports(self) -> None:
        result = open_path(resolve_project_paths(self.config.project_root).audit_progress_reports)
        if not result.success:
            self.result_panel.show_result(result)
