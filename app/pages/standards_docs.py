from __future__ import annotations

import time

try:
    from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget, QVBoxLayout, QWidget
except ImportError:  # pragma: no cover
    QGridLayout = QHBoxLayout = QLabel = QPushButton = QTableWidget = QVBoxLayout = QWidget = None

from app.page_async import AsyncRefreshMixin, log_page_performance
from app.page_tasks import run_tool_background
from app.pages.analysis_widgets import add_cards, counts_to_rows, populate_table
from app.widgets.report_viewer import ReportViewer
from app.widgets.tool_run_panel import ToolRunPanel
from core.documentation_gaps import generate_documentation_gap_report, scan_documentation_gaps
from core.openers import open_path
from core.paths import resolve_project_paths
from core.standards_compliance import analyze_standards_compliance, generate_standards_compliance_report


class StandardsDocsPage(AsyncRefreshMixin, QWidget):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self._init_async_refresh("standards_docs")
        layout = QVBoxLayout(self)
        heading = QLabel("Standards & Documentation")
        heading.setStyleSheet("font-size: 18pt; font-weight: 600;")
        layout.addWidget(heading)
        buttons = QHBoxLayout()
        for label, callback in [
            ("Run Documentation Gap Scan", self.run_report),
            ("Export Compliance Summary", self.run_compliance_report),
            ("Open Documentation Gap Reports Folder", self.open_reports),
            ("Refresh", lambda: self.refresh(force=True)),
        ]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            buttons.addWidget(button)
        layout.addLayout(buttons)
        grid = QGridLayout()
        self.cards = add_cards(
            grid,
            ["EOATs Scanned", "Total Gaps", "Critical Gaps", "Important Gaps", "Avg Compliance", "Standards Fails"],
        )
        layout.addLayout(grid)
        tables = QHBoxLayout()
        self.top_table = QTableWidget()
        self.missing_table = QTableWidget()
        self.compliance_table = QTableWidget()
        for label, table in [
            ("Top EOATs by Gap Count", self.top_table),
            ("Top Missing Fields", self.missing_table),
            ("Standards Compliance", self.compliance_table),
        ]:
            box = QVBoxLayout()
            box.addWidget(QLabel(label))
            box.addWidget(table)
            tables.addLayout(box)
        layout.addLayout(tables, stretch=1)
        self.preview = ReportViewer()
        layout.addWidget(self.preview, stretch=1)
        self.result_panel = ToolRunPanel()
        layout.addWidget(self.result_panel, stretch=1)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.on_show()

    def refresh(self, *_args, force: bool = False) -> bool:
        def _load() -> tuple:
            return (
                scan_documentation_gaps(self.config.project_root),
                analyze_standards_compliance(self.config.project_root),
            )

        return self._begin_background_refresh(
            task_id="standards_docs_refresh",
            name="Standards Documentation Refresh",
            load=_load,
            apply_result=self._apply_refresh_result,
            force=force,
            loading_text="Loading standards and documentation data in background...",
        )

    def on_show(self) -> None:
        self.refresh()
        return True

    def _apply_refresh_result(self, payload: tuple, data_load_seconds: float) -> None:
        (summary, error), (compliance, compliance_error) = payload
        if error:
            self.result_panel.show_result(error)
            return
        assert summary is not None
        if compliance_error:
            self.result_panel.show_result(compliance_error)
            return
        assert compliance is not None
        render_started = time.perf_counter()
        self.cards["EOATs Scanned"].set_value(str(summary.metrics.get("eoats_scanned", 0)))
        self.cards["Total Gaps"].set_value(str(summary.metrics.get("total_gaps", 0)))
        self.cards["Critical Gaps"].set_value(str(summary.metrics.get("critical_gaps", 0)))
        self.cards["Important Gaps"].set_value(str(summary.metrics.get("important_gaps", 0)))
        populate_table(
            self.top_table,
            summary.top_eoats,
            ["Audit ID", "Press/Machine #", "Gap Count", "Critical", "Important", "Nice-to-have"],
        )
        populate_table(
            self.missing_table,
            counts_to_rows(summary.missing_field_counts, "Missing Field"),
            ["Missing Field", "Count"],
        )
        self.cards["Avg Compliance"].set_value(str(compliance.metrics.get("average_compliance_score", 0)))
        self.cards["Standards Fails"].set_value(str(compliance.metrics.get("failed_standard_count", 0)))
        populate_table(
            self.compliance_table,
            [
                {
                    "Audit ID": audit.audit_id,
                    "Press/Machine #": audit.machine,
                    "Score": audit.overall_score,
                    "Fails": len(audit.failed_standards),
                    "Warnings": len(audit.warnings),
                    "Unknown": len(audit.unknown_items),
                }
                for audit in compliance.audits
            ],
            ["Audit ID", "Press/Machine #", "Score", "Fails", "Warnings", "Unknown"],
        )
        self.preview.show_markdown_text(summary.to_markdown() + "\n" + compliance.to_markdown())
        render_seconds = time.perf_counter() - render_started
        log_page_performance(
            self.config.project_root,
            "standards_docs",
            "data_load",
            data_load_seconds,
            details={
                "row_count": len(compliance.audits),
                "source_counts": {
                    "top_eoats": len(summary.top_eoats),
                    "missing_fields": len(summary.missing_field_counts),
                },
            },
        )
        log_page_performance(
            self.config.project_root,
            "standards_docs",
            "table_render",
            render_seconds,
            details={"row_count": len(summary.top_eoats) + len(compliance.audits)},
        )
        self.result_panel.show_text(f"Loaded standards documentation data in {data_load_seconds:.1f}s.")

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

    def run_compliance_report(self) -> None:
        run_tool_background(
            self.result_panel,
            "standards_compliance_report",
            "Standards Compliance Summary",
            lambda: generate_standards_compliance_report(self.config.project_root),
            self._report_finished,
            modifies_files=True,
        )

    def open_reports(self) -> None:
        result = open_path(resolve_project_paths(self.config.project_root).documentation_gap_reports)
        if not result.success:
            self.result_panel.show_result(result)
