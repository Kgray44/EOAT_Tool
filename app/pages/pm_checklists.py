from __future__ import annotations

try:
    from PySide6.QtWidgets import (
        QAbstractItemView,
        QCheckBox,
        QFormLayout,
        QGroupBox,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QPushButton,
        QTableWidget,
        QTableWidgetItem,
        QVBoxLayout,
        QWidget,
    )
except ImportError:  # pragma: no cover
    QAbstractItemView = QCheckBox = QFormLayout = QGroupBox = QHBoxLayout = QLabel = QLineEdit = QPushButton = QTableWidget = QTableWidgetItem = QVBoxLayout = QWidget = None

from app.page_tasks import run_tool_background
from app.widgets.report_viewer import ReportViewer
from app.widgets.tool_run_panel import ToolRunPanel
from core.openers import open_path
from core.paths import resolve_project_paths
from core.pm_checklists import generate_pm_checklists
from core.pm_due import PMRecord, build_pm_due_summary, export_pm_pack, mark_pm_item_complete, update_pm_record


class PmChecklistsPage(QWidget):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.pm_due_records: list[PMRecord] = []
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

        due_box = QGroupBox("PM Due Tracking")
        due_layout = QVBoxLayout(due_box)
        filter_form = QFormLayout()
        self.pm_machine_filter_edit = QLineEdit()
        self.pm_eoat_filter_edit = QLineEdit()
        self.pm_notes_edit = QLineEdit()
        self.pm_photo_link_edit = QLineEdit()
        self.pm_machine_filter_edit.setPlaceholderText("All machines")
        self.pm_eoat_filter_edit.setPlaceholderText("All EOAT types")
        self.pm_notes_edit.setPlaceholderText("Notes for selected item")
        self.pm_photo_link_edit.setPlaceholderText("Photo evidence link for selected item")
        filter_form.addRow("Machine filter", self.pm_machine_filter_edit)
        filter_form.addRow("EOAT type filter", self.pm_eoat_filter_edit)
        filter_form.addRow("Notes", self.pm_notes_edit)
        filter_form.addRow("Photo evidence link", self.pm_photo_link_edit)
        due_layout.addLayout(filter_form)

        due_buttons = QHBoxLayout()
        for label, callback in [
            ("Refresh PM Due", self.refresh_pm_due),
            ("Mark Complete", self.mark_selected_pm_complete),
            ("Add Notes", self.add_notes_to_selected_pm),
            ("Add Photo Evidence Link", self.add_photo_link_to_selected_pm),
            ("Export PM Pack", self.export_pm_pack),
        ]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            due_buttons.addWidget(button)
        due_layout.addLayout(due_buttons)
        self.pm_due_summary_label = QLabel("PM due tracking has not been refreshed yet.")
        due_layout.addWidget(self.pm_due_summary_label)
        self.pm_due_table = QTableWidget(0, 8)
        self.pm_due_table.setHorizontalHeaderLabels(["Status", "Due Date", "Machine", "Audit ID", "EOAT Type", "Item", "Notes", "Evidence"])
        self.pm_due_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.pm_due_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.pm_due_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.pm_due_table.verticalHeader().setVisible(False)
        self.pm_due_table.setAlternatingRowColors(True)
        due_layout.addWidget(self.pm_due_table)
        layout.addWidget(due_box, stretch=2)

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

    def _show_pm_summary(self, summary) -> None:
        self.pm_due_records = list(summary.records)
        metrics = summary.metrics
        self.pm_due_summary_label.setText(
            " | ".join(
                [
                    f"Due this week: {metrics.get('due_this_week', 0)}",
                    f"Overdue: {metrics.get('overdue', 0)}",
                    f"Completed recently: {metrics.get('completed_recently', 0)}",
                    f"Blocked: {metrics.get('blocked', 0)}",
                ]
            )
        )
        self.pm_due_table.setRowCount(len(self.pm_due_records))
        for row_index, record in enumerate(self.pm_due_records):
            values = [
                record.status,
                record.due_date,
                record.machine,
                record.audit_id,
                record.eoat_type,
                record.item_label,
                record.notes,
                record.photo_evidence_link,
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value or ""))
                item.setData(256, record.record_id)
                self.pm_due_table.setItem(row_index, column, item)
        self.pm_due_table.resizeColumnsToContents()

    def _selected_pm_record(self) -> PMRecord | None:
        selected = self.pm_due_table.selectionModel().selectedRows() if hasattr(self, "pm_due_table") else []
        if not selected:
            return self.pm_due_records[0] if self.pm_due_records else None
        row = selected[0].row()
        if 0 <= row < len(self.pm_due_records):
            return self.pm_due_records[row]
        return None

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

    def refresh_pm_due(self) -> None:
        run_tool_background(
            self.result_panel,
            "pm_due_refresh",
            "Refresh PM Due",
            lambda: build_pm_due_summary(
                self.config.project_root,
                machine=self.pm_machine_filter_edit.text().strip() or None,
                eoat_type=self.pm_eoat_filter_edit.text().strip() or None,
            ),
            self._show_pm_summary,
            modifies_files=False,
        )

    def mark_selected_pm_complete(self) -> None:
        record = self._selected_pm_record()
        if record is None:
            self.result_panel.show_text("Refresh PM due tracking and select an item first.")
            return
        run_tool_background(
            self.result_panel,
            "pm_due_complete",
            "Mark PM Complete",
            lambda: mark_pm_item_complete(
                self.config.project_root,
                record.record_id,
                notes=self.pm_notes_edit.text().strip(),
                photo_evidence_link=self.pm_photo_link_edit.text().strip(),
            ),
            self._pm_update_finished,
            modifies_files=True,
        )

    def add_notes_to_selected_pm(self) -> None:
        record = self._selected_pm_record()
        if record is None:
            self.result_panel.show_text("Refresh PM due tracking and select an item first.")
            return
        run_tool_background(
            self.result_panel,
            "pm_due_notes",
            "Add PM Notes",
            lambda: update_pm_record(self.config.project_root, record.record_id, notes=self.pm_notes_edit.text().strip()),
            self._pm_update_finished,
            modifies_files=True,
        )

    def add_photo_link_to_selected_pm(self) -> None:
        record = self._selected_pm_record()
        if record is None:
            self.result_panel.show_text("Refresh PM due tracking and select an item first.")
            return
        run_tool_background(
            self.result_panel,
            "pm_due_evidence",
            "Add PM Evidence Link",
            lambda: update_pm_record(self.config.project_root, record.record_id, photo_evidence_link=self.pm_photo_link_edit.text().strip()),
            self._pm_update_finished,
            modifies_files=True,
        )

    def export_pm_pack(self) -> None:
        run_tool_background(
            self.result_panel,
            "pm_due_export",
            "Export PM Pack",
            lambda: export_pm_pack(
                self.config.project_root,
                machine=self.pm_machine_filter_edit.text().strip() or None,
                eoat_type=self.pm_eoat_filter_edit.text().strip() or None,
            ),
            self._show_result,
            modifies_files=True,
        )

    def _pm_update_finished(self, result) -> None:
        self.result_panel.show_result(result)
        self.refresh_pm_due()

    def open_folder(self) -> None:
        result = open_path(resolve_project_paths(self.config.project_root).pm_generated_checklists)
        if not result.success:
            self.result_panel.show_result(result)
