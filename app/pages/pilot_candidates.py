from __future__ import annotations

import time

try:
    from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget, QVBoxLayout, QWidget
except ImportError:  # pragma: no cover
    QGridLayout = QHBoxLayout = QLabel = QPushButton = QTableWidget = QVBoxLayout = QWidget = None

from app.page_async import AsyncRefreshMixin, log_page_performance
from app.page_tasks import run_tool_background
from app.pages.analysis_widgets import add_cards, populate_table
from app.widgets.report_viewer import ReportViewer
from app.widgets.tool_run_panel import ToolRunPanel
from core.openers import open_path
from core.paths import resolve_project_paths
from core.pilot_evidence_packets import generate_pilot_evidence_packet
from core.pilot_roi import export_pilot_roi_report
from core.pilot_scoring import generate_pilot_ranking_report, rank_pilot_candidates


class PilotCandidatesPage(AsyncRefreshMixin, QWidget):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self._init_async_refresh("pilot_candidates")
        layout = QVBoxLayout(self)
        heading = QLabel("Pilot Candidates")
        heading.setStyleSheet("font-size: 18pt; font-weight: 600;")
        layout.addWidget(heading)
        buttons = QHBoxLayout()
        for label, callback in [
            ("Run Pilot Ranking", self.run_report),
            ("Generate Evidence Packet", self.generate_evidence_packet),
            ("Export ROI Justification", self.export_roi_justification),
            ("Open Candidate Reports Folder", self.open_reports),
            ("Refresh", lambda: self.refresh(force=True)),
        ]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            buttons.addWidget(button)
        layout.addLayout(buttons)
        grid = QGridLayout()
        self.cards = add_cards(grid, ["Candidates Evaluated", "Top Candidate", "Top Score", "Confidence"])
        layout.addLayout(grid)
        self.table = QTableWidget()
        layout.addWidget(self.table, stretch=1)
        self.preview = ReportViewer()
        layout.addWidget(self.preview, stretch=1)
        self.result_panel = ToolRunPanel()
        layout.addWidget(self.result_panel, stretch=1)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.on_show()

    def refresh(self, *_args, force: bool = False) -> bool:
        return self._begin_background_refresh(
            task_id="pilot_candidates_refresh",
            name="Pilot Candidates Refresh",
            load=lambda: rank_pilot_candidates(self.config.project_root),
            apply_result=self._apply_refresh_result,
            force=force,
            loading_text="Loading pilot candidates in background...",
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
        top = summary.ranked_candidates[0] if summary.ranked_candidates else {}
        self.cards["Candidates Evaluated"].set_value(str(summary.metrics.get("candidates_evaluated", 0)))
        self.cards["Top Candidate"].set_value(str(summary.metrics.get("top_candidate", "No data yet")))
        self.cards["Top Score"].set_value(str(summary.metrics.get("top_score", 0)))
        self.cards["Confidence"].set_value(str(top.get("Confidence", "No data yet")))
        populate_table(
            self.table,
            summary.ranked_candidates,
            [
                "Rank",
                "Candidate ID",
                "Press/Machine #",
                "Main Problem",
                "Total Score",
                "Confidence",
                "Missing Evidence",
                "Score Explanation",
            ],
        )
        self.preview.show_markdown_text(summary.to_markdown())
        render_seconds = time.perf_counter() - render_started
        log_page_performance(
            self.config.project_root,
            "pilot_candidates",
            "data_load",
            data_load_seconds,
            details={"row_count": len(summary.ranked_candidates)},
        )
        log_page_performance(
            self.config.project_root,
            "pilot_candidates",
            "table_render",
            render_seconds,
            details={"row_count": len(summary.ranked_candidates)},
        )
        self.result_panel.show_text(f"Loaded {len(summary.ranked_candidates)} pilot candidate(s) in {data_load_seconds:.1f}s.")

    def run_report(self) -> None:
        run_tool_background(
            self.result_panel,
            "pilot_ranking_report",
            "Pilot Candidate Ranking",
            lambda: generate_pilot_ranking_report(self.config.project_root),
            self._report_finished,
            modifies_files=True,
        )

    def _report_finished(self, result) -> None:
        if result.output_reports:
            self.preview.load_report_file(result.output_reports[0])

    def open_reports(self) -> None:
        result = open_path(resolve_project_paths(self.config.project_root).pilot_project / "Candidate_Cells")
        if not result.success:
            self.result_panel.show_result(result)

    def generate_evidence_packet(self) -> None:
        row = self.table.currentRow()
        candidate_id = ""
        machine = ""
        if row >= 0:
            headers = [self.table.horizontalHeaderItem(index).text() for index in range(self.table.columnCount())]
            values = {header: self.table.item(row, index).text() if self.table.item(row, index) else "" for index, header in enumerate(headers)}
            candidate_id = values.get("Candidate ID", "")
            machine = values.get("Press/Machine #", "")
        run_tool_background(
            self.result_panel,
            "pilot_evidence_packet",
            "Pilot Candidate Evidence Packet",
            lambda: generate_pilot_evidence_packet(self.config.project_root, candidate_id=candidate_id, machine=machine),
            self._report_finished,
            modifies_files=True,
        )

    def export_roi_justification(self) -> None:
        row = self.table.currentRow()
        candidate_id = ""
        if row >= 0:
            headers = [self.table.horizontalHeaderItem(index).text() for index in range(self.table.columnCount())]
            values = {header: self.table.item(row, index).text() if self.table.item(row, index) else "" for index, header in enumerate(headers)}
            candidate_id = values.get("Candidate ID", "")
        run_tool_background(
            self.result_panel,
            "pilot_roi_report",
            "Pilot ROI Justification",
            lambda: export_pilot_roi_report(self.config.project_root, candidate_id=candidate_id),
            self._report_finished,
            modifies_files=True,
        )
