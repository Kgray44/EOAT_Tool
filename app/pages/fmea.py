from __future__ import annotations

import time

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import (
        QGridLayout,
        QHBoxLayout,
        QLabel,
        QPushButton,
        QTableWidget,
        QTableWidgetItem,
        QVBoxLayout,
        QWidget,
    )
except ImportError:  # pragma: no cover
    Qt = None
    QGridLayout = QHBoxLayout = QLabel = QPushButton = QTableWidget = QTableWidgetItem = QVBoxLayout = QWidget = None

from app.page_async import AsyncRefreshMixin, log_page_performance
from app.page_tasks import run_tool_background
from app.pages.analysis_widgets import add_cards, populate_table
from app.widgets.report_viewer import ReportViewer
from app.widgets.tool_run_panel import ToolRunPanel
from core.fmea_analysis import analyze_fmea, generate_fmea_report
from core.fmea_suggestions import accept_fmea_suggestions, export_fmea_evidence_report, reject_fmea_suggestions
from core.openers import open_path
from core.paths import resolve_project_paths


class FmeaPage(AsyncRefreshMixin, QWidget):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self._init_async_refresh("fmea")
        layout = QVBoxLayout(self)
        heading = QLabel("FMEA-Lite")
        heading.setStyleSheet("font-size: 18pt; font-weight: 600;")
        layout.addWidget(heading)
        buttons = QHBoxLayout()
        workflow = QLabel(
            "Workflow: 1. Run analysis  ->  2. Review suggestions  ->  3. Check RPN  ->  4. Export/open report"
        )
        workflow.setStyleSheet("color: #627d98;")
        layout.addWidget(workflow)
        for label, callback in [
            ("Run FMEA Analysis", self.run_report),
            ("Calculate RPN / Refresh", lambda: self.refresh(force=True)),
            ("Suggest FMEA Entries", lambda: self.refresh(force=True)),
            ("Open FMEA Reports Folder", self.open_reports),
        ]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            buttons.addWidget(button)
        for label, callback in [
            ("Accept Selected", self.accept_selected_suggestions),
            ("Edit Before Accepting", self.edit_before_accepting),
            ("Reject Selected", self.reject_selected_suggestions),
            ("Export Evidence Report", self.export_suggestion_draft),
        ]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            buttons.addWidget(button)
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

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.on_show()

    def refresh(self, *_args, force: bool = False) -> bool:
        return self._begin_background_refresh(
            task_id="fmea_refresh",
            name="FMEA Refresh",
            load=lambda: analyze_fmea(self.config.project_root),
            apply_result=self._apply_refresh_result,
            force=force,
            loading_text="Loading FMEA analysis in background...",
        )

    def on_show(self) -> None:
        self.refresh()
        return True

    def _apply_refresh_result(self, payload: tuple, data_load_seconds: float) -> None:
        summary, error = payload
        if error:
            self.result_panel.show_result(error)
            return
        assert summary is not None
        render_started = time.perf_counter()
        self.cards["Existing Rows"].set_value(str(summary.metrics.get("existing_fmea_rows", 0)))
        self.cards["Suggested Entries"].set_value(str(summary.metrics.get("suggested_entries", 0)))
        self.cards["Missing Risk Rows"].set_value(str(summary.metrics.get("missing_risk_rows", 0)))
        self.cards["Top RPN"].set_value(str(summary.metrics.get("top_rpn", 0)))
        populate_table(
            self.risk_table,
            summary.ranked_rows[:10],
            ["FMEA ID", "Press/Machine #", "Failure Mode", "RPN", "Recommended Action"],
        )
        self._populate_suggestion_table(summary.suggestions)
        self.preview.show_markdown_text(summary.to_markdown())
        render_seconds = time.perf_counter() - render_started
        log_page_performance(
            self.config.project_root,
            "fmea",
            "data_load",
            data_load_seconds,
            details={"row_count": len(summary.ranked_rows), "source_counts": {"suggestions": len(summary.suggestions)}},
        )
        log_page_performance(
            self.config.project_root,
            "fmea",
            "table_render",
            render_seconds,
            details={"row_count": len(summary.ranked_rows[:10]) + len(summary.suggestions)},
        )
        self.result_panel.show_text(f"Loaded FMEA analysis in {data_load_seconds:.1f}s.")

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

    def _populate_suggestion_table(self, suggestions: list[dict]) -> None:
        columns = [
            "Accept",
            "Failure Mode",
            "Confidence",
            "Calculated RPN",
            "Evidence",
            "Suggested Severity",
            "Suggested Frequency",
            "Suggested Detectability",
            "Suggested Mitigation",
            "Source Fields/Tags",
        ]
        sorting = self.suggest_table.isSortingEnabled()
        self.suggest_table.setSortingEnabled(False)
        self.suggest_table.blockSignals(True)
        self.suggest_table.setUpdatesEnabled(False)
        self.suggest_table.setColumnCount(len(columns))
        self.suggest_table.setHorizontalHeaderLabels(columns)
        self.suggest_table.setRowCount(len(suggestions))
        for row_index, suggestion in enumerate(suggestions):
            accept_item = QTableWidgetItem("")
            accept_item.setCheckState(Qt.CheckState.Unchecked)
            accept_item.setData(Qt.ItemDataRole.UserRole, suggestion)
            self.suggest_table.setItem(row_index, 0, accept_item)
            for col_index, column in enumerate(columns[1:], start=1):
                item = QTableWidgetItem(str(suggestion.get(column, "")))
                if column not in {
                    "Suggested Severity",
                    "Suggested Frequency",
                    "Suggested Detectability",
                    "Suggested Mitigation",
                }:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.suggest_table.setItem(row_index, col_index, item)
        self.suggest_table.resizeColumnsToContents()
        self.suggest_table.setUpdatesEnabled(True)
        self.suggest_table.blockSignals(False)
        self.suggest_table.setSortingEnabled(sorting)

    def _selected_suggestion_rows(self) -> list[dict]:
        rows: list[dict] = []
        columns = [
            "Accept",
            "Failure Mode",
            "Confidence",
            "Calculated RPN",
            "Evidence",
            "Suggested Severity",
            "Suggested Frequency",
            "Suggested Detectability",
            "Suggested Mitigation",
            "Source Fields/Tags",
        ]
        for row_index in range(self.suggest_table.rowCount()):
            accept_item = self.suggest_table.item(row_index, 0)
            if accept_item is None or accept_item.checkState() != Qt.CheckState.Checked:
                continue
            data = dict(accept_item.data(Qt.ItemDataRole.UserRole) or {})
            for col_index, column in enumerate(columns[1:], start=1):
                item = self.suggest_table.item(row_index, col_index)
                data[column] = item.text().strip() if item is not None else ""
            rows.append(data)
        return rows

    def accept_selected_suggestions(self) -> None:
        result = accept_fmea_suggestions(self.config.project_root, self._selected_suggestion_rows())
        self.result_panel.show_result(result)
        if result.success:
            self.refresh(force=True)

    def edit_before_accepting(self) -> None:
        self.result_panel.show_text(
            "Edit Severity, Frequency, Detectability, and Mitigation directly in the suggestion table, "
            "then check Accept and click Accept Selected. Numeric risk values are required before workbook write-back."
        )

    def reject_selected_suggestions(self) -> None:
        rows = self._selected_suggestion_rows()
        result = reject_fmea_suggestions(
            self.config.project_root,
            [row.get("Suggestion ID", "") for row in rows],
            reason="Rejected in FMEA page review.",
        )
        self.result_panel.show_result(result)
        if result.success:
            self.refresh(force=True)

    def export_suggestion_draft(self) -> None:
        rows = self._selected_suggestion_rows() or [
            dict(self.suggest_table.item(row, 0).data(Qt.ItemDataRole.UserRole) or {})
            for row in range(self.suggest_table.rowCount())
        ]
        result = export_fmea_evidence_report(self.config.project_root, rows)
        self.result_panel.show_result(result)
        if result.output_reports:
            self.preview.load_report_file(result.output_reports[0])
