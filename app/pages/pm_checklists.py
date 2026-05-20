from __future__ import annotations

try:
    from PySide6.QtWidgets import QCheckBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QTextEdit, QVBoxLayout, QWidget
except ImportError:  # pragma: no cover
    QCheckBox = QFormLayout = QGroupBox = QHBoxLayout = QLabel = QLineEdit = QPushButton = QTextEdit = QVBoxLayout = QWidget = None

from app.widgets.report_viewer import ReportViewer
from app.widgets.tool_run_panel import ToolRunPanel
from app.page_tasks import run_tool_background
from core.openers import open_path
from core.paths import resolve_project_paths
from core.pm_checklists import generate_pm_checklists


class PmChecklistsPage(QWidget):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        layout = QVBoxLayout(self)
        heading = QLabel("PM Checklists")
        heading.setStyleSheet("font-size: 18pt; font-weight: 600;")
        layout.addWidget(heading)

        target_box = QGroupBox("Target EOAT / Audit ID")
        form = QFormLayout(target_box)
        self.audit_id_edit = QLineEdit()
        self.press_edit = QLineEdit()
        form.addRow("Audit ID", self.audit_id_edit)
        form.addRow("Press/Machine #", self.press_edit)
        layout.addWidget(target_box)

        options_box = QGroupBox("Generation Scope and Output Options")
        options_layout = QVBoxLayout(options_box)
        self.all_check = QCheckBox("Generate for all audited EOATs")
        self.generic_check = QCheckBox("Generate generic templates")
        self.docx_check = QCheckBox("Also create DOCX")
        options_layout.addWidget(self.all_check)
        options_layout.addWidget(self.generic_check)
        options_layout.addWidget(self.docx_check)
        layout.addWidget(options_box)

        buttons = QHBoxLayout()
        for label, callback in [
            ("Generate PM Checklist", self.generate_selected),
            ("Generate Generic Templates", self.generate_generic),
            ("Open Checklist Folder", self.open_folder),
        ]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            buttons.addWidget(button)
        layout.addLayout(buttons)

        self.result_panel = ToolRunPanel()
        layout.addWidget(self.result_panel, stretch=1)
        layout.addWidget(QLabel("Latest generated checklist preview"))
        self.preview = ReportViewer()
        self.preview.setPlaceholderText("No checklist generated yet. Generate a checklist to preview the latest Markdown output.")
        self.preview.setMaximumHeight(260)
        layout.addWidget(self.preview, stretch=2)

    def _formats(self) -> list[str]:
        formats = ["markdown"]
        if self.docx_check.isChecked():
            formats.append("docx")
        return formats

    def _show_result(self, result) -> None:
        self.result_panel.show_result(result)
        if result.output_reports:
            markdown_reports = [path for path in result.output_reports if str(path).lower().endswith(".md")]
            if markdown_reports:
                self.preview.load_report_file(markdown_reports[0])

    def generate_selected(self) -> None:
        run_tool_background(
            self.result_panel,
            "pm_checklist_generate",
            "Generate PM Checklist",
            lambda: generate_pm_checklists(
                self.config.project_root,
                audit_id=self.audit_id_edit.text().strip() or None,
                press=self.press_edit.text().strip() or None,
                all_audited=self.all_check.isChecked(),
                generic=self.generic_check.isChecked(),
                formats=self._formats(),
            ),
            self._show_result,
            modifies_files=True,
        )

    def generate_generic(self) -> None:
        run_tool_background(
            self.result_panel,
            "pm_checklist_generic",
            "Generate Generic PM Templates",
            lambda: generate_pm_checklists(self.config.project_root, generic=True, formats=self._formats()),
            self._show_result,
            modifies_files=True,
        )

    def open_folder(self) -> None:
        result = open_path(resolve_project_paths(self.config.project_root).pm_generated_checklists)
        if not result.success:
            self.result_panel.show_result(result)
