from __future__ import annotations

try:
    from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget
except ImportError:  # pragma: no cover
    QGridLayout = QHBoxLayout = QLabel = QPushButton = QVBoxLayout = QWidget = None

from app.widgets.status_card import StatusCard
from app.widgets.tool_run_panel import ToolRunPanel
from app.page_tasks import run_tool_background
from core.audit_by_press import REFRESH_ACTION_NAME, refresh_audit_by_press_view_action
from core.openers import open_path
from core.paths import resolve_project_paths
from core.validation import run_foundation_validation


class WorkbookHealthPage(QWidget):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        layout = QVBoxLayout(self)
        heading = QLabel("Workbook Health")
        heading.setStyleSheet("font-size: 18pt; font-weight: 600;")
        layout.addWidget(heading)

        button_row = QHBoxLayout()
        for label, callback in [
            ("Run Foundation Validation", self.run_validation),
            (REFRESH_ACTION_NAME, self.refresh_audit_by_press_view),
            ("Open Validation Reports Folder", self.open_validation_reports),
            ("Open Master Workbook", self.open_master_workbook),
        ]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            button_row.addWidget(button)
        layout.addLayout(button_row)

        grid = QGridLayout()
        self.cards = {}
        for index, key in enumerate(["Workbook Status", "Missing Sheets", "Missing Headers", "Schedule Files", "Last Validation"]):
            card = StatusCard(key)
            self.cards[key] = card
            grid.addWidget(card, index // 5, index % 5)
        layout.addLayout(grid)

        self.result_panel = ToolRunPanel()
        layout.addWidget(self.result_panel, stretch=1)
        self.result_panel.show_text("No validation report selected. Run foundation validation to generate a workbook health report.")

    def run_validation(self) -> None:
        run_tool_background(
            self.result_panel,
            "workbook_foundation_validation",
            "Foundation Validation",
            lambda: run_foundation_validation(self.config.project_root),
            self._validation_finished,
            modifies_files=True,
        )

    def refresh_audit_by_press_view(self) -> None:
        run_tool_background(
            self.result_panel,
            "audit_by_press_refresh",
            REFRESH_ACTION_NAME,
            lambda: refresh_audit_by_press_view_action(self.config.project_root),
            modifies_files=True,
            workbook_lock=True,
        )

    def _validation_finished(self, result) -> None:
        self.cards["Workbook Status"].set_value("OK" if result.success else "Needs attention")
        missing_sheets = max(0, int(result.metrics.get("expected_sheet_count", 0)) - int(result.metrics.get("actual_sheet_count", 0)))
        self.cards["Missing Sheets"].set_value(str(missing_sheets))
        self.cards["Missing Headers"].set_value(str(result.metrics.get("missing_key_inventory_header_count", 0)))
        self.cards["Schedule Files"].set_value(str(result.metrics.get("schedule_week_count", 0)))
        self.cards["Last Validation"].set_value("Just now")

    def open_validation_reports(self) -> None:
        result = open_path(resolve_project_paths(self.config.project_root).validation_reports)
        if not result.success:
            self.result_panel.show_result(result)

    def open_master_workbook(self) -> None:
        result = open_path(resolve_project_paths(self.config.project_root).master_workbook)
        if not result.success:
            self.result_panel.show_result(result)
