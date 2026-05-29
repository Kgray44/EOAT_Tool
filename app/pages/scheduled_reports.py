from __future__ import annotations

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import (
        QAbstractItemView,
        QApplication,
        QComboBox,
        QGridLayout,
        QHBoxLayout,
        QLabel,
        QPushButton,
        QScrollArea,
        QTableWidget,
        QTableWidgetItem,
        QVBoxLayout,
        QWidget,
    )
except ImportError:  # pragma: no cover
    QApplication = QAbstractItemView = QComboBox = QGridLayout = QHBoxLayout = QLabel = QPushButton = QScrollArea = QTableWidget = QTableWidgetItem = QVBoxLayout = QWidget = None
    Qt = None

from app.event_bus import EVENT_REPORT_GENERATED, EVENT_SCHEDULED_REPORT_RAN, get_event_bus
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
    preview_summary_schedule,
    run_actual_scheduled_task_now,
    run_catch_up_summaries,
    run_daily_summary_now,
    run_scheduler_preflight,
    run_weekly_summary_now,
    scheduled_tools_log_path,
    uninstall_schedules,
)


class ScheduledReportsPage(QWidget):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.cards: dict[str, StatusCard] = {}
        self.preview_rows: list[dict] = []
        self.preflight_rows: list[dict] = []
        self.latest_output_report = ""

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
            "The page previews upcoming/missed runs, checks the task setup, and runs duplicate-safe catch-up summaries."
        )
        help_label.setWordWrap(True)
        content_layout.addWidget(help_label)

        top_row = QHBoxLayout()
        for label, callback in [
            ("Refresh Scheduled Status", self.refresh_status),
            ("Run Preflight Diagnostics", self.run_preflight),
            ("Open Scheduled Tool Log", self.open_scheduled_log),
            ("Copy Diagnostics", self.copy_diagnostics),
        ]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            top_row.addWidget(button)
        self.actual_task_combo = QComboBox()
        self.actual_task_combo.addItem("Daily Summary", "daily_summary")
        self.actual_task_combo.addItem("Weekly Summary", "weekly_summary")
        top_row.addWidget(self.actual_task_combo)
        actual_task_button = QPushButton("Run Actual Scheduled Task Now")
        actual_task_button.clicked.connect(self.run_actual_scheduled_task)
        top_row.addWidget(actual_task_button)
        top_row.addStretch(1)
        content_layout.addLayout(top_row)

        action_row = QHBoxLayout()
        for label, callback in [
            ("Run Daily Dry Run", self.run_daily_dry_run),
            ("Run Weekly Dry Run", self.run_weekly_dry_run),
            ("Generate Daily Now", self.run_daily_now),
            ("Generate Weekly Now", self.run_weekly_now),
            ("Install/Repair Tasks", self.install_schedules),
            ("Uninstall Tasks", self.uninstall_schedules),
            ("Open Reports Folder", self.open_reports_folder),
            ("Open Latest Generated Report", self.open_latest_generated_report),
        ]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            action_row.addWidget(button)
        action_row.addStretch(1)
        content_layout.addLayout(action_row)

        grid = QGridLayout()
        card_names = [
            "Daily Schedule",
            "Daily Task Installed",
            "Daily Task Result",
            "Daily Last Status",
            "Daily Last Run",
            "Daily Last Report",
            "Daily Next Run",
            "Daily Missed",
            "Weekly Schedule",
            "Weekly Task Installed",
            "Weekly Task Result",
            "Weekly Last Status",
            "Weekly Last Run",
            "Weekly Last Report",
            "Weekly Next Run",
            "Weekly Missed",
            "Reports Folders",
            "Scheduled Tool Log",
            "Emergency Log",
        ]
        for index, key in enumerate(card_names):
            card = StatusCard(key)
            self.cards[key] = card
            grid.addWidget(card, index // 4, index % 4)
        content_layout.addLayout(grid)

        preview_heading = QLabel("Calendar Preview")
        preview_heading.setStyleSheet("font-size: 13pt; font-weight: 600;")
        content_layout.addWidget(preview_heading)

        preview_controls = QHBoxLayout()
        self.days_combo = QComboBox()
        self.days_combo.addItems(["14 days", "30 days"])
        preview_controls.addWidget(QLabel("Window"))
        preview_controls.addWidget(self.days_combo)
        for label, callback in [
            ("Refresh Preview", self.refresh_preview),
            ("Catch Up Selected Daily", lambda: self.catch_up_selected("daily_summary")),
            ("Catch Up Selected Weekly", lambda: self.catch_up_selected("weekly_summary")),
            ("Catch Up All Missed", lambda: self.catch_up_selected("all")),
        ]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            preview_controls.addWidget(button)
        preview_controls.addStretch(1)
        content_layout.addLayout(preview_controls)

        self.preview_table = QTableWidget(0, 9)
        self.preview_table.setHorizontalHeaderLabels(["Date", "Weekday", "Automation", "Time", "Status", "Week", "Day", "Existing Report", "Reason"])
        self.preview_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.preview_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.preview_table.setMinimumHeight(240)
        content_layout.addWidget(self.preview_table)

        diagnostics_heading = QLabel("Preflight Diagnostics")
        diagnostics_heading.setStyleSheet("font-size: 13pt; font-weight: 600;")
        content_layout.addWidget(diagnostics_heading)
        self.preflight_table = QTableWidget(0, 4)
        self.preflight_table.setHorizontalHeaderLabels(["Check", "Status", "Message", "Details"])
        self.preflight_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.preflight_table.setMinimumHeight(180)
        content_layout.addWidget(self.preflight_table)

        self.result_panel = ToolRunPanel()
        content_layout.addWidget(self.result_panel)
        self.refresh_status()
        self.refresh_preview()
        self.run_preflight()

    def on_show(self) -> None:
        self.refresh_status()
        self.refresh_preview()

    def on_event(self, _event) -> None:
        self.refresh_status()
        self.refresh_preview()

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

    def refresh_preview(self) -> None:
        days = 30 if self.days_combo.currentText().startswith("30") else 14
        rows = preview_summary_schedule(self.config.project_root, days=days)
        self.preview_rows = [row.to_dict() for row in rows]
        self._populate_table(
            self.preview_table,
            self.preview_rows,
            ["date", "weekday", "expected_automation_type", "scheduled_time", "status", "week", "day", "existing_report_path", "decision_reason"],
        )

    def run_preflight(self) -> None:
        self.result_panel.show_text("Running scheduled report preflight diagnostics...")
        get_task_manager().run_task(
            TaskRequest(
                id="scheduled_reports_preflight",
                name="Scheduled Reports Preflight",
                category="scheduled_reports",
                callable=run_scheduler_preflight,
                args=(self.config.project_root,),
            ),
            on_finished=self._apply_preflight_result,
        )

    def _task_text(self, task: dict) -> str:
        installed = task.get("installed")
        if installed is True:
            return f"Yes ({task.get('state') or 'state unknown'})"
        if installed is False:
            return "No"
        return f"Unknown: {task.get('warning', '')}".strip()

    def _task_result_text(self, task: dict) -> str:
        installed = task.get("installed")
        if installed is False:
            return "Not installed"
        raw = str(task.get("last_result_raw") or task.get("last_result") or "").strip()
        description = str(task.get("last_result_description") or "").strip()
        if not raw and not description:
            return "No run recorded"
        if raw and description:
            return f"{raw} - {description}"
        return raw or description

    def _apply_status_result(self, task_result) -> None:
        if not task_result.ok:
            self.result_panel.show_text(task_result.message)
            return
        status = task_result.result_data
        daily = status.get("daily", {})
        weekly = status.get("weekly", {})
        paths = status.get("paths", {})
        self._set_card("Daily Schedule", daily.get("schedule", "Monday-Thursday at 7:00 PM"))
        self._set_card("Daily Task Installed", self._task_text(daily.get("task", {})))
        self._set_card("Daily Task Result", self._task_result_text(daily.get("task", {})))
        self._set_card("Daily Last Status", daily.get("report_generation_result") or daily.get("last_status") or "No report-generation log recorded")
        self._set_card("Daily Last Run", daily.get("task", {}).get("last_run_time") or daily.get("last_log_line") or "No run recorded")
        self._set_card("Daily Last Report", daily.get("last_report") or "No daily summary found")
        self._set_card("Daily Next Run", daily.get("next_expected_run") or "")
        self._set_card("Daily Missed", ", ".join(daily.get("missed_dates", [])) or "None detected")
        self._set_card("Weekly Schedule", weekly.get("schedule", "Friday at 7:00 PM"))
        self._set_card("Weekly Task Installed", self._task_text(weekly.get("task", {})))
        self._set_card("Weekly Task Result", self._task_result_text(weekly.get("task", {})))
        self._set_card("Weekly Last Status", weekly.get("report_generation_result") or weekly.get("last_status") or "No report-generation log recorded")
        self._set_card("Weekly Last Run", weekly.get("task", {}).get("last_run_time") or weekly.get("last_log_line") or "No run recorded")
        self._set_card("Weekly Last Report", weekly.get("last_report") or "No weekly summary found")
        self._set_card("Weekly Next Run", weekly.get("next_expected_run") or "")
        self._set_card("Weekly Missed", ", ".join(weekly.get("missed_dates", [])) or "None detected")
        self._set_card("Reports Folders", f"Daily: {paths.get('daily_reports', '')}\nWeekly: {paths.get('weekly_reports', '')}")
        self._set_card("Scheduled Tool Log", status.get("scheduled_log", "Not configured"))
        self._set_card("Emergency Log", status.get("emergency_log", "Not configured"))
        self.result_panel.show_text("Scheduled report status refreshed.")

    def _apply_preflight_result(self, task_result) -> None:
        tool_result = task_result.to_tool_result()
        self.result_panel.show_result(tool_result)
        self.preflight_rows = list((tool_result.structured_data or {}).get("checks") or [])
        self._populate_table(self.preflight_table, self.preflight_rows, ["name", "status", "message", "details"])

    def _populate_table(self, table: QTableWidget, rows: list[dict], columns: list[str]) -> None:
        table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            for col_index, key in enumerate(columns):
                item = QTableWidgetItem(str(row.get(key, "") or ""))
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                table.setItem(row_index, col_index, item)
        table.resizeColumnsToContents()

    def _after_report_action(self, result) -> None:
        created_reports = [path for path in result.output_reports if path in result.files_created]
        if created_reports:
            self.latest_output_report = created_reports[0]
        if result.success and created_reports:
            get_event_bus().emit(EVENT_SCHEDULED_REPORT_RAN, {"outputs": created_reports}, source="ScheduledReportsPage")
            get_event_bus().emit(EVENT_REPORT_GENERATED, {"outputs": created_reports}, source="ScheduledReportsPage")
        self.refresh_status()
        self.refresh_preview()

    def _require_created_report(self, result):
        if result.success and not result.files_created:
            result.success = False
            result.summary = f"{result.summary} No new report file was created."
            result.warnings.append("No new report file was created; report generation was skipped or only an existing report was found.")
        return result

    def run_daily_dry_run(self) -> None:
        run_tool_background(
            self.result_panel,
            "scheduled_reports_daily_dry_run",
            "Run Daily Dry Run",
            lambda: self._require_created_report(run_daily_summary_now(self.config.project_root, scheduled=False, dry_run=True, decision_reason="manual daily dry run")),
            self._after_report_action,
            modifies_files=True,
        )

    def run_weekly_dry_run(self) -> None:
        run_tool_background(
            self.result_panel,
            "scheduled_reports_weekly_dry_run",
            "Run Weekly Dry Run",
            lambda: self._require_created_report(run_weekly_summary_now(self.config.project_root, scheduled=False, dry_run=True, notes="Manual dry run from Scheduled Reports page.")),
            self._after_report_action,
            modifies_files=True,
        )

    def run_daily_now(self) -> None:
        run_tool_background(
            self.result_panel,
            "scheduled_reports_daily_now",
            "Generate Daily Now",
            lambda: self._require_created_report(run_daily_summary_now(self.config.project_root, scheduled=False)),
            self._after_report_action,
            modifies_files=True,
        )

    def run_weekly_now(self) -> None:
        run_tool_background(
            self.result_panel,
            "scheduled_reports_weekly_now",
            "Generate Weekly Now",
            lambda: self._require_created_report(run_weekly_summary_now(self.config.project_root, scheduled=False)),
            self._after_report_action,
            modifies_files=True,
        )

    def run_actual_scheduled_task(self) -> None:
        automation = self.actual_task_combo.currentData() or "daily_summary"
        run_tool_background(
            self.result_panel,
            "scheduled_reports_actual_task_now",
            "Run Actual Scheduled Task Now",
            lambda: run_actual_scheduled_task_now(self.config.project_root, automation=str(automation)),
            self._after_report_action,
            modifies_files=True,
        )

    def catch_up_selected(self, automation: str) -> None:
        dates = self._selected_preview_dates(automation)
        if not dates:
            self.result_panel.show_text("Select one or more missed preview rows, or refresh the preview to detect missed report dates.")
            return
        run_tool_background(
            self.result_panel,
            "scheduled_reports_catch_up",
            "Scheduled Report Catch-Up",
            lambda: self._require_created_report(run_catch_up_summaries(self.config.project_root, dates, automation=automation)),
            self._after_report_action,
            modifies_files=True,
        )

    def _selected_preview_dates(self, automation: str) -> list[str]:
        selected_rows = sorted({index.row() for index in self.preview_table.selectionModel().selectedRows()})
        rows = [self.preview_rows[index] for index in selected_rows] if selected_rows else self.preview_rows
        dates: list[str] = []
        for row in rows:
            if row.get("status") != "missed":
                continue
            row_automation = str(row.get("expected_automation_type") or "")
            if automation != "all" and row_automation != automation:
                continue
            dates.append(str(row.get("date")))
        return dates

    def install_schedules(self) -> None:
        run_tool_background(
            self.result_panel,
            "scheduled_reports_install",
            "Install/Repair Tasks",
            lambda: install_or_repair_schedules(self.config.project_root),
            lambda _result: (self.refresh_status(), self.run_preflight()),
            modifies_files=False,
        )

    def uninstall_schedules(self) -> None:
        run_tool_background(
            self.result_panel,
            "scheduled_reports_uninstall",
            "Uninstall Tasks",
            lambda: uninstall_schedules(self.config.project_root),
            lambda _result: (self.refresh_status(), self.run_preflight()),
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

    def open_latest_generated_report(self) -> None:
        if not self.latest_output_report:
            self.result_panel.show_text("No generated report path has been recorded in this session yet.")
            return
        result = open_path(self.latest_output_report)
        if not result.success:
            self.result_panel.show_result(result)

    def copy_diagnostics(self) -> None:
        lines = ["Scheduled Reports Diagnostics", ""]
        for key, card in self.cards.items():
            lines.append(f"{key}: {card.value_label.text()}")
        lines.extend(["", "Calendar Preview:"])
        lines.extend(
            f"{row.get('date')} {row.get('expected_automation_type') or 'none'} {row.get('status')}: {row.get('decision_reason')}"
            for row in self.preview_rows
        )
        lines.extend(["", "Preflight:"])
        lines.extend(f"{row.get('status')}: {row.get('name')} - {row.get('message')}" for row in self.preflight_rows)
        text = "\n".join(lines)
        app = QApplication.instance()
        if app is not None:
            app.clipboard().setText(text)
        self.result_panel.show_text("Scheduled report diagnostics copied to the clipboard.")
