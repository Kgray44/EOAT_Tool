from __future__ import annotations

try:
    from PySide6.QtWidgets import (
        QCheckBox,
        QComboBox,
        QHBoxLayout,
        QLabel,
        QListWidget,
        QPushButton,
        QSpinBox,
        QTableWidget,
        QTableWidgetItem,
        QTextEdit,
        QVBoxLayout,
        QWidget,
    )
except ImportError:  # pragma: no cover
    QCheckBox = QComboBox = QHBoxLayout = QLabel = QListWidget = QPushButton = QSpinBox = QTableWidget = (
        QTableWidgetItem
    ) = QTextEdit = QVBoxLayout = QWidget = None

from app.page_tasks import run_tool_background
from app.widgets.report_viewer import ReportViewer
from app.widgets.tool_run_panel import ToolRunPanel
from core.morning_planner import generate_morning_plan
from core.schedule import available_schedule_weeks, load_week_schedule, resolve_project_day_for_project
from core.task_progress import STATUS_VALUES, progress_file_for_week, update_task_status


class SchedulePage(QWidget):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.current_schedule = None
        layout = QVBoxLayout(self)
        heading = QLabel("Schedule")
        heading.setStyleSheet("font-size: 18pt; font-weight: 600;")
        layout.addWidget(heading)

        top_row = QHBoxLayout()
        self.week_combo = QComboBox()
        self.week_combo.currentIndexChanged.connect(self.load_selected_week)
        refresh_button = QPushButton("Refresh Schedule")
        refresh_button.clicked.connect(self.refresh)
        self.day_spin = QSpinBox()
        self.day_spin.setRange(1, 7)
        self.day_spin.setValue(1)
        self.override_checkbox = QCheckBox("Use selected Week/Day override")
        self.override_checkbox.toggled.connect(self.update_resolved_day_preview)
        self.morning_button = QPushButton("Generate Morning Plan")
        self.morning_button.clicked.connect(self.generate_morning_plan)
        self.day_spin.valueChanged.connect(self.update_resolved_day_preview)
        top_row.addWidget(QLabel("Week"))
        top_row.addWidget(self.week_combo)
        top_row.addWidget(QLabel("Day"))
        top_row.addWidget(self.day_spin)
        top_row.addWidget(self.override_checkbox)
        top_row.addWidget(refresh_button)
        top_row.addWidget(self.morning_button)
        layout.addLayout(top_row)

        self.notes_edit = QTextEdit()
        self.notes_edit.setPlaceholderText("Optional morning-plan notes")
        self.notes_edit.setMaximumHeight(90)
        layout.addWidget(self.notes_edit)

        self.summary_label = QLabel("")
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)
        self.resolved_label = QLabel("")
        self.resolved_label.setWordWrap(True)
        layout.addWidget(self.resolved_label)

        layout.addWidget(QLabel("Planned tasks by day"))
        self.day_list = QListWidget()
        layout.addWidget(self.day_list)

        layout.addWidget(QLabel("Task progress"))
        self.task_table = QTableWidget()
        self.task_table.setColumnCount(4)
        self.task_table.setHorizontalHeaderLabels(["Task", "Status", "Day", "ID"])
        layout.addWidget(self.task_table, stretch=1)

        status_row = QHBoxLayout()
        for status in STATUS_VALUES:
            button = QPushButton(status)
            button.clicked.connect(lambda _checked=False, value=status: self.mark_selected(value))
            status_row.addWidget(button)
        layout.addLayout(status_row)
        self.result_panel = ToolRunPanel()
        layout.addWidget(self.result_panel, stretch=1)
        self.preview = ReportViewer()
        self.preview.setMaximumHeight(220)
        layout.addWidget(self.preview, stretch=1)
        self.refresh()

    def refresh(self) -> None:
        self.week_combo.blockSignals(True)
        self.week_combo.clear()
        weeks = available_schedule_weeks(self.config.project_root)
        for week in weeks:
            self.week_combo.addItem(str(week), week)
        self.week_combo.blockSignals(False)
        if weeks:
            self.week_combo.setCurrentIndex(0)
            self.load_selected_week()
        else:
            self.summary_label.setText(
                "No schedule/task progress week files found. Add project_schedule_weekN.json "
                "or task_progress_weekN.json files under 00_Project_Admin, then refresh."
            )
            self.day_list.clear()
            self.task_table.setRowCount(0)
            self.update_resolved_day_preview()

    def load_selected_week(self) -> None:
        week = self.week_combo.currentData()
        if week is None:
            return
        self.current_schedule = load_week_schedule(self.config.project_root, int(week))
        counts = ", ".join(f"{key}: {value}" for key, value in self.current_schedule.status_counts.items())
        self.summary_label.setText(
            f"Week {week} | Schedule: {self.current_schedule.schedule_path or 'missing'} | "
            f"Progress: {self.current_schedule.progress_path or 'missing'} | {counts}"
        )
        self.day_list.clear()
        for day, tasks in self.current_schedule.days.items():
            self.day_list.addItem(f"Day {day}")
            for task in tasks:
                self.day_list.addItem(f"  - {task}")
        self.task_table.setRowCount(len(self.current_schedule.tasks))
        for row, task in enumerate(self.current_schedule.tasks):
            values = [task.description, task.status, task.day, task.id]
            for col, value in enumerate(values):
                self.task_table.setItem(row, col, QTableWidgetItem(str(value)))
        self.task_table.resizeColumnsToContents()
        self.task_table.setColumnWidth(0, 520)
        self.update_resolved_day_preview()

    def _resolved_day(self):
        week = self.week_combo.currentData()
        return resolve_project_day_for_project(
            self.config.project_root,
            project_start_date=self.config.project_start_date,
            skip_weekends=self.config.skip_weekends,
            holidays=self.config.holidays,
            manual_week=int(week) if week is not None else 1,
            manual_day=self.day_spin.value(),
            manual_override=self.override_checkbox.isChecked(),
        )

    def update_resolved_day_preview(self) -> None:
        resolved = self._resolved_day()
        label = f"Resolved: Week {resolved.week} Day {resolved.day} from {resolved.source}"
        if resolved.warning:
            label += f" ({resolved.warning})"
        selected_week = self.week_combo.currentData()
        selected_day = self.day_spin.value()
        auto_day = resolve_project_day_for_project(
            self.config.project_root,
            project_start_date=self.config.project_start_date,
            skip_weekends=self.config.skip_weekends,
            holidays=self.config.holidays,
        )
        if (
            not self.override_checkbox.isChecked()
            and selected_week is not None
            and (int(selected_week) != auto_day.week or selected_day != auto_day.day)
        ):
            label += "\nSelected day differs from today's resolved project day. Enable manual override to use selected values."
        self.resolved_label.setText(label)
        suffix = " (manual override)" if self.override_checkbox.isChecked() else ""
        self.morning_button.setText(f"Generate Morning Plan for Week {resolved.week} Day {resolved.day}{suffix}")

    def mark_selected(self, status: str) -> None:
        if self.current_schedule is None:
            return
        row = self.task_table.currentRow()
        if row < 0:
            return
        task_id_item = self.task_table.item(row, 3)
        if task_id_item is None:
            return
        progress_path = self.current_schedule.progress_path or progress_file_for_week(
            self.config.project_root, self.current_schedule.week
        )
        if update_task_status(progress_path, task_id_item.text(), status):
            self.load_selected_week()

    def generate_morning_plan(self) -> None:
        week = self.week_combo.currentData()
        override = self.override_checkbox.isChecked()
        if week is None and override:
            self.result_panel.show_text("Select or create a schedule week before generating a morning plan.")
            return
        run_tool_background(
            self.result_panel,
            "schedule_morning_plan",
            "Morning Plan",
            lambda: generate_morning_plan(
                self.config.project_root,
                week=int(week) if override else None,
                day=self.day_spin.value() if override else None,
                notes=self.notes_edit.toPlainText(),
                detail_level="todo",
                project_start_date=self.config.project_start_date,
                skip_weekends=self.config.skip_weekends,
                holidays=self.config.holidays,
                manual_override=override,
            ),
            self._morning_finished,
            modifies_files=True,
        )

    def _morning_finished(self, result) -> None:
        if result.output_reports:
            self.preview.load_report_file(result.output_reports[0])
