from __future__ import annotations

import sys
from datetime import date

try:
    from PySide6.QtWidgets import (
        QCheckBox,
        QDialog,
        QDialogButtonBox,
        QFormLayout,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QListWidget,
        QPushButton,
        QSpinBox,
        QSplitter,
        QTableWidget,
        QTableWidgetItem,
        QTextEdit,
        QVBoxLayout,
        QWidget,
    )
except ImportError:  # pragma: no cover
    QCheckBox = QDialog = QDialogButtonBox = QFormLayout = QHBoxLayout = QLabel = QLineEdit = QListWidget = QPushButton = QSpinBox = QSplitter = QTableWidget = QTableWidgetItem = QTextEdit = QVBoxLayout = QWidget = None

from app.page_tasks import run_tool_background
from app.widgets.report_viewer import ReportViewer
from app.widgets.tool_run_panel import ToolRunPanel
from core.constants import TOOLKIT_ROOT
from core.mentor_brief import generate_mentor_brief
from core.openers import open_path
from core.paths import resolve_project_paths
from core.reports import report_folders
from core.tool_runner import run_python_script
from core.weekly_summary import generate_weekly_summary


class DailySummaryDialog(QDialog):
    def __init__(self, project_root: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Run Daily Summary Tool")
        self.project_root_edit = QLineEdit(project_root)
        self.week_spin = QSpinBox()
        self.week_spin.setRange(1, 12)
        self.week_spin.setValue(1)
        self.day_spin = QSpinBox()
        self.day_spin.setRange(1, 5)
        self.day_spin.setValue(1)
        self.git_check = QCheckBox("Include Git")
        self.snapshot_check = QCheckBox("Include Snapshot")
        self.interactive_check = QCheckBox("Interactive")

        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.addRow("Project root", self.project_root_edit)
        form.addRow("Week", self.week_spin)
        form.addRow("Day", self.day_spin)
        form.addRow("", self.git_check)
        form.addRow("", self.snapshot_check)
        form.addRow("", self.interactive_check)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def command_args(self) -> list[str]:
        args = [
            "--project-root",
            self.project_root_edit.text(),
            "--week",
            str(self.week_spin.value()),
            "--day",
            str(self.day_spin.value()),
        ]
        if self.git_check.isChecked():
            args.append("--include-git")
        if self.snapshot_check.isChecked():
            args.append("--include-snapshot")
        if self.interactive_check.isChecked():
            args.append("--interactive")
        else:
            args.extend(
                [
                    "--completed",
                    "Reviewed EOAT Command Center dashboard status",
                    "--need",
                    "Confirm next EOAT project priority with mentor or supervisor",
                    "--plan",
                    "Continue EOAT project execution from the current schedule",
                    "--note",
                    "Generated from EOAT Command Center dashboard.",
                ]
            )
        return args

    def is_interactive(self) -> bool:
        return self.interactive_check.isChecked()


class WeeklySummaryDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Generate Weekly Summary")
        self.week_spin = QSpinBox()
        self.week_spin.setRange(1, 12)
        self.week_spin.setValue(1)
        self.notes_edit = QTextEdit()
        self.notes_edit.setPlaceholderText("Optional manual notes for this weekly summary")
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.addRow("Week", self.week_spin)
        layout.addLayout(form)
        layout.addWidget(self.notes_edit)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class MentorBriefDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Generate Mentor Brief")
        self.days_spin = QSpinBox()
        self.days_spin.setRange(1, 30)
        self.days_spin.setValue(7)
        self.since_edit = QLineEdit()
        self.since_edit.setPlaceholderText("Optional ISO date, e.g. 2026-05-18")
        self.notes_edit = QTextEdit()
        self.notes_edit.setPlaceholderText("Optional meeting notes or context")
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.addRow("Last N days", self.days_spin)
        form.addRow("Since date", self.since_edit)
        layout.addLayout(form)
        layout.addWidget(self.notes_edit)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class ReportsPage(QWidget):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.folder_rows = []
        layout = QVBoxLayout(self)
        heading = QLabel("Reports")
        heading.setStyleSheet("font-size: 18pt; font-weight: 600;")
        layout.addWidget(heading)

        button_row = QHBoxLayout()
        for label, callback in [
            ("Refresh", self.refresh),
            ("Open Selected Folder", self.open_selected_folder),
            ("Launch Daily Summary Tool", self.launch_daily_status_tool),
            ("Generate Weekly Summary", self.generate_weekly_summary),
            ("Generate Mentor Brief", self.generate_mentor_brief),
        ]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            button_row.addWidget(button)
        layout.addLayout(button_row)

        splitter = QSplitter()
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(QLabel("Report folders"))
        self.folder_table = QTableWidget()
        self.folder_table.setColumnCount(3)
        self.folder_table.setHorizontalHeaderLabels(["Folder", "Exists?", "Path"])
        self.folder_table.currentCellChanged.connect(self.populate_files_for_selected_folder)
        left_layout.addWidget(self.folder_table)
        self.file_list = QListWidget()
        self.file_list.currentItemChanged.connect(self.preview_selected_file)
        left_layout.addWidget(QLabel("Recent files"))
        left_layout.addWidget(self.file_list)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.addWidget(QLabel("Report preview"))
        self.preview = ReportViewer()
        self.preview.setPlaceholderText("No report selected. Select a folder and a Markdown/text report to preview it here.")
        right_layout.addWidget(self.preview, stretch=2)
        self.result_panel = ToolRunPanel()
        right_layout.addWidget(self.result_panel, stretch=1)
        splitter.addWidget(right)
        splitter.setSizes([430, 700])
        layout.addWidget(splitter, stretch=1)
        self.refresh()

    def refresh(self) -> None:
        self.folder_rows = report_folders(self.config.project_root)
        self.folder_table.setRowCount(len(self.folder_rows))
        for row, folder in enumerate(self.folder_rows):
            values = [folder.label, "Yes" if folder.exists else "No", str(folder.path)]
            for col, value in enumerate(values):
                self.folder_table.setItem(row, col, QTableWidgetItem(value))
        self.folder_table.resizeColumnsToContents()
        if self.folder_rows:
            self.folder_table.selectRow(0)
            self.populate_files_for_selected_folder()

    def populate_files_for_selected_folder(self, *_args) -> None:
        self.file_list.clear()
        row = self.folder_table.currentRow()
        if row < 0 or row >= len(self.folder_rows):
            return
        for path in self.folder_rows[row].recent_files:
            self.file_list.addItem(str(path))

    def preview_selected_file(self, current, _previous=None) -> None:
        if current is None:
            return
        self.preview.load_report_file(current.text())

    def open_selected_folder(self) -> None:
        row = self.folder_table.currentRow()
        if row < 0 or row >= len(self.folder_rows):
            return
        result = open_path(self.folder_rows[row].path)
        if not result.success:
            self.result_panel.show_result(result)

    def launch_daily_status_tool(self) -> None:
        dialog = DailySummaryDialog(self.config.project_root, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        script = TOOLKIT_ROOT / "daily_status_summary.py"
        args = dialog.command_args()
        command_text = " ".join([sys.executable, str(script), *[f'"{arg}"' if " " in arg else arg for arg in args]])
        if dialog.is_interactive():
            self.result_panel.show_text(
                "Interactive mode should be run in a terminal so the dashboard does not hang.\n\n"
                f"Command:\n{command_text}"
            )
            return

        paths = resolve_project_paths(dialog.project_root_edit.text())
        report_path = paths.daily_reports / f"Week{dialog.week_spin.value()}_Day{dialog.day_spin.value()}_Status_{date.today().isoformat()}.md"
        if report_path.exists():
            self.result_panel.show_text(
                "A report for this week/day/date already exists, so the dashboard did not run the command automatically.\n\n"
                f"Run manually if you want to decide about overwrite prompts:\n{command_text}"
            )
            return
        run_tool_background(
            self.result_panel,
            "reports_daily_status",
            "Daily Status Summary Generator",
            lambda: run_python_script(
                script,
                args=args,
                cwd=TOOLKIT_ROOT,
                tool_id="daily_status_summary",
                tool_name="Daily Status Summary Generator",
                timeout_seconds=60,
                project_root_for_log=self.config.project_root,
            ),
            lambda _result: self.refresh(),
            modifies_files=True,
        )

    def generate_weekly_summary(self) -> None:
        dialog = WeeklySummaryDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        run_tool_background(
            self.result_panel,
            "reports_weekly_summary",
            "Weekly Summary",
            lambda: generate_weekly_summary(
                self.config.project_root,
                week=dialog.week_spin.value(),
                notes=dialog.notes_edit.toPlainText(),
            ),
            self._report_finished,
            modifies_files=True,
        )

    def generate_mentor_brief(self) -> None:
        dialog = MentorBriefDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        run_tool_background(
            self.result_panel,
            "reports_mentor_brief",
            "Mentor Brief",
            lambda: generate_mentor_brief(
                self.config.project_root,
                days=dialog.days_spin.value(),
                since=dialog.since_edit.text().strip() or None,
                notes=dialog.notes_edit.toPlainText(),
            ),
            self._report_finished,
            modifies_files=True,
        )

    def _report_finished(self, result) -> None:
        if result.output_reports:
            self.preview.load_report_file(result.output_reports[0])
        self.refresh()
