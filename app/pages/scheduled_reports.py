from __future__ import annotations

try:
    from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget
except ImportError:  # pragma: no cover
    QGridLayout = QHBoxLayout = QLabel = QPushButton = QScrollArea = QVBoxLayout = QWidget = None

from app.page_tasks import run_tool_background
from app.task_runner import TaskRequest, get_task_manager
from app.ui_constants import PAGE_MARGIN, SECTION_SPACING
from app.widgets.status_card import StatusCard
from app.widgets.tool_run_panel import ToolRunPanel
from core.openers import open_path
from core.paths import resolve_project_paths
from core.scheduled_reports import (
    get_scheduled_report_status,
    install_or_repair_schedules,
    run_daily_summary_now,
    run_weekly_summary_now,
    scheduled_tools_log_path,
    uninstall_schedules,
)


class ScheduledReportsPage(QWidget):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.cards: dict[str, StatusCard] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        scroll.setWidget(content)
        layout.addWidget(scroll)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(PAGE_MARGIN, PAGE_MARGIN, PAGE_MARGIN, PAGE_MARGIN)
        content_layout.setSpacing(SECTION_SPACING)

        heading = QLabel("Scheduled Reports")
        heading.setStyleSheet("font-size: 18pt; font-weight: 600;")
        content_layout.addWidget(heading)
        help_label = QLabel(
            "Windows Task Scheduler runs daily summaries Monday-Thursday at 7:00 PM and weekly summaries Friday at 7:00 PM. "
            "The dashboard shows status and lets you run safe catch-up summaries without keeping the app open."
        )
        help_label.setWordWrap(True)
        content_layout.addWidget(help_label)

        button_row = QHBoxLayout()
        actions = [
            ("Refresh Scheduled Status", self.refresh_status),
            ("Run Daily Summary Now", self.run_daily_now),
            ("Run Weekly Summary Now", self.run_weekly_now),
            ("Install/Repair Scheduled Tasks", self.install_schedules),
            ("Uninstall Scheduled Tasks", self.uninstall_schedules),
            ("Open Reports Folder", self.open_reports_folder),
            ("Open Scheduled Tool Log", self.open_scheduled_log),
        ]
        for label, callback in actions:
            button = QPushButton(label)
            button.clicked.connect(callback)
            button_row.addWidget(button)
        button_row.addStretch(1)
        content_layout.addLayout(button_row)

        grid = QGridLayout()
        for index, key in enumerate(
            [
                "Daily Schedule",
                "Daily Task Installed",
                "Daily Last Run",
                "Daily Last Report",
                "Daily Missed",
                "Weekly Schedule",
                "Weekly Task Installed",
                "Weekly Last Run",
                "Weekly Last Report",
                "Weekly Missed",
                "Scheduled Tool Log",
            ]
        ):
            card = StatusCard(key)
            self.cards[key] = card
            grid.addWidget(card, index // 3, index % 3)
        content_layout.addLayout(grid)

        self.result_panel = ToolRunPanel()
        content_layout.addWidget(self.result_panel)
        self.refresh_status()

    def _set_card(self, key: str, value: str) -> None:
        card = self.cards.get(key)
        if card is not None:
            card.set_value(str(value))

    def refresh_status(self) -> None:
        self.result_panel.show_text("Checking scheduled report status...")
        get_task_manager().run_task(
            TaskRequest(
                id="scheduled_reports_refresh",
                name="Scheduled Reports Status",
                category="scheduled_reports",
                callable=get_scheduled_report_status,
                args=(self.config.project_root,),
            ),
            on_finished=self._apply_status_result,
        )

    def _task_text(self, task: dict) -> str:
        installed = task.get("installed")
        if installed is True:
            return f"Yes ({task.get('state') or 'state unknown'})"
        if installed is False:
            return "No"
        return f"Unknown: {task.get('warning', '')}".strip()

    def _apply_status_result(self, task_result) -> None:
        if not task_result.ok:
            self.result_panel.show_text(task_result.message)
            return
        status = task_result.result_data
        daily = status.get("daily", {})
        weekly = status.get("weekly", {})
        self._set_card("Daily Schedule", daily.get("schedule", "Monday-Thursday at 7:00 PM"))
        self._set_card("Daily Task Installed", self._task_text(daily.get("task", {})))
        self._set_card("Daily Last Run", daily.get("task", {}).get("last_run_time") or daily.get("last_log_line") or "No run recorded")
        self._set_card("Daily Last Report", daily.get("last_report") or "No daily summary found")
        self._set_card("Daily Missed", ", ".join(daily.get("missed_dates", [])) or "None detected")
        self._set_card("Weekly Schedule", weekly.get("schedule", "Friday at 7:00 PM"))
        self._set_card("Weekly Task Installed", self._task_text(weekly.get("task", {})))
        self._set_card("Weekly Last Run", weekly.get("task", {}).get("last_run_time") or weekly.get("last_log_line") or "No run recorded")
        self._set_card("Weekly Last Report", weekly.get("last_report") or "No weekly summary found")
        self._set_card("Weekly Missed", ", ".join(weekly.get("missed_dates", [])) or "None detected")
        self._set_card("Scheduled Tool Log", status.get("scheduled_log", "Not configured"))
        self.result_panel.show_text("Scheduled report status refreshed.")

    def run_daily_now(self) -> None:
        run_tool_background(
            self.result_panel,
            "scheduled_reports_daily_now",
            "Run Daily Summary Now",
            lambda: run_daily_summary_now(self.config.project_root, scheduled=False),
            lambda _result: self.refresh_status(),
            modifies_files=True,
        )

    def run_weekly_now(self) -> None:
        run_tool_background(
            self.result_panel,
            "scheduled_reports_weekly_now",
            "Run Weekly Summary Now",
            lambda: run_weekly_summary_now(self.config.project_root, scheduled=False),
            lambda _result: self.refresh_status(),
            modifies_files=True,
        )

    def install_schedules(self) -> None:
        run_tool_background(
            self.result_panel,
            "scheduled_reports_install",
            "Install/Repair Scheduled Tasks",
            lambda: install_or_repair_schedules(self.config.project_root),
            lambda _result: self.refresh_status(),
            modifies_files=False,
        )

    def uninstall_schedules(self) -> None:
        run_tool_background(
            self.result_panel,
            "scheduled_reports_uninstall",
            "Uninstall Scheduled Tasks",
            lambda: uninstall_schedules(self.config.project_root),
            lambda _result: self.refresh_status(),
            modifies_files=False,
        )

    def open_reports_folder(self) -> None:
        result = open_path(resolve_project_paths(self.config.project_root).project_admin)
        if not result.success:
            self.result_panel.show_result(result)

    def open_scheduled_log(self) -> None:
        result = open_path(scheduled_tools_log_path(self.config.project_root))
        if not result.success:
            self.result_panel.show_result(result)
