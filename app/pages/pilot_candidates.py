from __future__ import annotations

try:
    from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget, QVBoxLayout, QWidget
except ImportError:  # pragma: no cover
    QGridLayout = QHBoxLayout = QLabel = QPushButton = QTableWidget = QVBoxLayout = QWidget = None

from app.pages.analysis_widgets import add_cards, populate_table
from app.page_tasks import run_tool_background
from app.widgets.report_viewer import ReportViewer
from app.widgets.tool_run_panel import ToolRunPanel
from core.openers import open_path
from core.paths import resolve_project_paths
from core.pilot_scoring import generate_pilot_ranking_report, rank_pilot_candidates


class PilotCandidatesPage(QWidget):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        layout = QVBoxLayout(self)
        heading = QLabel("Pilot Candidates")
        heading.setStyleSheet("font-size: 18pt; font-weight: 600;")
        layout.addWidget(heading)
        buttons = QHBoxLayout()
        for label, callback in [("Run Pilot Ranking", self.run_report), ("Open Candidate Reports Folder", self.open_reports), ("Refresh", self.refresh)]:
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
        self.refresh()

    def refresh(self) -> None:
        summary, error = rank_pilot_candidates(self.config.project_root)
        if error:
            self.result_panel.show_result(error)
            return
        assert summary is not None
        top = summary.ranked_candidates[0] if summary.ranked_candidates else {}
        self.cards["Candidates Evaluated"].set_value(str(summary.metrics.get("candidates_evaluated", 0)))
        self.cards["Top Candidate"].set_value(str(summary.metrics.get("top_candidate", "No data yet")))
        self.cards["Top Score"].set_value(str(summary.metrics.get("top_score", 0)))
        self.cards["Confidence"].set_value(str(top.get("Confidence", "No data yet")))
        populate_table(self.table, summary.ranked_candidates, ["Rank", "Candidate ID", "Press/Machine #", "Main Problem", "Total Score", "Confidence", "Missing Data"])
        self.preview.show_markdown_text(summary.to_markdown())

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
