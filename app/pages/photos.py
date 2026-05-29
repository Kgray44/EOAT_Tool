from __future__ import annotations

from datetime import date

try:
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QComboBox,
        QFormLayout,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QListWidget,
        QListWidgetItem,
        QPushButton,
        QTableWidget,
        QTableWidgetItem,
        QTextEdit,
        QVBoxLayout,
        QWidget,
    )
except ImportError:  # pragma: no cover
    QApplication = QCheckBox = QComboBox = QFormLayout = QHBoxLayout = QLabel = QLineEdit = QListWidget = QListWidgetItem = QPushButton = QTableWidget = QTableWidgetItem = QTextEdit = QVBoxLayout = QWidget = None

from app.page_tasks import run_tool_background
from app.widgets.tool_run_panel import ToolRunPanel
from core.openers import open_path
from core.paths import resolve_project_paths
from core.photo_evidence import (
    audit_photo_intake_folder,
    create_audit_photo_intake_folder,
    evidence_coverage_for_audit,
    export_photo_checklist,
    indexed_photos_for_audit,
    link_photo_to_audit_field,
    resolve_indexed_photo_path,
)
from core.photo_indexing import PHOTO_VIEW_FOLDERS, intake_photos, list_incoming_photos, preview_photo_intake


class PhotosPage(QWidget):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        layout = QVBoxLayout(self)
        heading = QLabel("EOAT Photo Intake")
        heading.setStyleSheet("font-size: 18pt; font-weight: 600;")
        layout.addWidget(heading)

        top = QHBoxLayout()
        left = QVBoxLayout()
        button_row = QHBoxLayout()
        for label, callback in [
            ("Refresh Incoming Photos", self.refresh_incoming),
            ("Open Incoming Photos Folder", self.open_incoming),
            ("Open Cell Photos Folder", self.open_cell_photos),
        ]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            button_row.addWidget(button)
        left.addLayout(button_row)
        self.incoming_list = QListWidget()
        self.incoming_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        incoming_label = QLabel("Incoming photos")
        incoming_label.setStyleSheet("font-weight: 600;")
        left.addWidget(incoming_label)
        self.empty_hint = QLabel("")
        self.empty_hint.setWordWrap(True)
        self.empty_hint.setStyleSheet("color: #627d98;")
        left.addWidget(self.empty_hint)
        left.addWidget(self.incoming_list)
        top.addLayout(left, stretch=2)

        form_container = QWidget()
        form = QFormLayout(form_container)
        self.plant_edit = QLineEdit()
        self.press_edit = QLineEdit()
        self.date_edit = QLineEdit(date.today().isoformat())
        self.view_combo = QComboBox()
        self.view_combo.addItems(list(PHOTO_VIEW_FOLDERS.keys()))
        self.audit_id_edit = QLineEdit()
        self.issue_id_edit = QLineEdit()
        self.audit_field_link_edit = QLineEdit()
        self.description_edit = QTextEdit()
        self.description_edit.setFixedHeight(70)
        self.notes_edit = QTextEdit()
        self.notes_edit.setFixedHeight(60)
        self.copy_check = QCheckBox("Copy photos instead of moving originals")
        self.copy_check.setChecked(True)
        for label, widget in [
            ("Plant/Area", self.plant_edit),
            ("Press/Machine #", self.press_edit),
            ("Date Taken", self.date_edit),
            ("EOAT Area Shown", self.view_combo),
            ("Related Audit ID", self.audit_id_edit),
            ("Related Issue ID", self.issue_id_edit),
            ("Link to Audit Field", self.audit_field_link_edit),
            ("Description", self.description_edit),
            ("Notes", self.notes_edit),
            ("", self.copy_check),
        ]:
            form.addRow(label, widget)
        preview_button = QPushButton("Preview Rename/Move")
        preview_button.clicked.connect(self.preview_plan)
        confirm_button = QPushButton("Confirm Intake")
        confirm_button.clicked.connect(self.confirm_intake)
        form.addRow(preview_button, confirm_button)
        top.addWidget(form_container, stretch=1)
        layout.addLayout(top, stretch=2)

        evidence_heading = QLabel("Audit Photo Evidence")
        evidence_heading.setStyleSheet("font-size: 13pt; font-weight: 600;")
        layout.addWidget(evidence_heading)
        evidence_actions = QHBoxLayout()
        for label, callback in [
            ("Refresh Evidence Coverage", self.refresh_evidence_coverage),
            ("Create Audit Intake Folder", self.create_audit_intake_folder),
            ("Export Photo Checklist", self.export_audit_photo_checklist),
            ("Copy Intake Path", self.copy_audit_intake_path),
            ("Open Audit Intake Folder", self.open_audit_intake_folder),
            ("Refresh Indexed Photos", self.refresh_indexed_photos),
        ]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            evidence_actions.addWidget(button)
        layout.addLayout(evidence_actions)
        self.missing_shots_label = QLabel("")
        self.missing_shots_label.setWordWrap(True)
        self.missing_shots_label.setStyleSheet("color: #9f1239; font-weight: 600;")
        layout.addWidget(self.missing_shots_label)
        self.evidence_table = QTableWidget(0, 7)
        self.evidence_table.setHorizontalHeaderLabels(["Category", "Applies", "Required", "Present", "Photos", "Status", "Warning"])
        layout.addWidget(self.evidence_table, stretch=1)

        indexed_heading = QLabel("Indexed Photos for Audit")
        indexed_heading.setStyleSheet("font-weight: 600;")
        layout.addWidget(indexed_heading)
        indexed_actions = QHBoxLayout()
        for label, callback in [
            ("Open Photo", self.open_selected_indexed_photo),
            ("Link Photo to Audit Field", self.link_selected_photo_to_field),
        ]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            indexed_actions.addWidget(button)
        layout.addLayout(indexed_actions)
        self.indexed_photos_table = QTableWidget(0, 5)
        self.indexed_photos_table.setHorizontalHeaderLabels(["Photo ID", "Area", "Filename", "Path", "Linked Field"])
        layout.addWidget(self.indexed_photos_table, stretch=1)

        self.result_panel = ToolRunPanel()
        layout.addWidget(self.result_panel, stretch=1)
        self.refresh_incoming()

    def refresh_incoming(self) -> None:
        self.incoming_list.clear()
        photos = list_incoming_photos(self.config.project_root)
        paths = resolve_project_paths(self.config.project_root)
        for photo in photos:
            self.incoming_list.addItem(QListWidgetItem(str(photo)))
        if not photos:
            self.empty_hint.setText(
                "No incoming photos found.\n"
                "1. Click Open Incoming Photos Folder.\n"
                "2. Drop JPG, JPEG, PNG, or HEIC images there.\n"
                "3. Click Refresh Incoming Photos.\n"
                "4. Fill metadata and confirm intake."
            )
            self.result_panel.show_text(f"Incoming folder:\n{paths.incoming_photos}")
        else:
            self.empty_hint.setText(f"{len(photos)} supported photo(s) ready for intake.")

    def selected_photos(self) -> list[str]:
        return [item.text() for item in self.incoming_list.selectedItems()]

    def metadata(self) -> dict[str, str]:
        return {
            "plant_area": self.plant_edit.text().strip(),
            "press_machine": self.press_edit.text().strip(),
            "date_taken": self.date_edit.text().strip(),
            "view_type": self.view_combo.currentText(),
            "related_audit_id": self.audit_id_edit.text().strip(),
            "related_issue_id": self.issue_id_edit.text().strip(),
            "audit_field_link": self.audit_field_link_edit.text().strip(),
            "description": self.description_edit.toPlainText().strip(),
            "notes": self.notes_edit.toPlainText().strip(),
        }

    def preview_plan(self) -> None:
        data = self.metadata()
        plan = preview_photo_intake(
            self.config.project_root,
            self.selected_photos(),
            data["plant_area"],
            data["press_machine"],
            data["date_taken"],
            data["view_type"],
        )
        if not plan:
            self.result_panel.show_text("No selected supported photos to preview.")
            return
        self.result_panel.show_text("\n".join(f"{item.source} -> {item.target}" for item in plan))

    def confirm_intake(self) -> None:
        data = self.metadata()
        run_tool_background(
            self.result_panel,
            "photo_intake_confirm",
            "Photo Intake",
            lambda: intake_photos(
                self.config.project_root,
                self.selected_photos(),
                data["plant_area"],
                data["press_machine"],
                data["date_taken"],
                data["view_type"],
                related_audit_id=data["related_audit_id"],
                related_issue_id=data["related_issue_id"],
                description=data["description"],
                notes=self._notes_with_field_link(data["notes"], data["audit_field_link"]),
                copy_mode=self.copy_check.isChecked(),
            ),
            self._intake_finished,
            modifies_files=True,
            workbook_lock=True,
        )

    def _intake_finished(self, result) -> None:
        if result.success:
            self.refresh_incoming()
            self.refresh_evidence_coverage()

    def open_incoming(self) -> None:
        result = open_path(resolve_project_paths(self.config.project_root).incoming_photos)
        if not result.success:
            self.result_panel.show_result(result)

    def open_cell_photos(self) -> None:
        result = open_path(resolve_project_paths(self.config.project_root).cell_photos)
        if not result.success:
            self.result_panel.show_result(result)

    def refresh_evidence_coverage(self) -> None:
        audit_id = self.audit_id_edit.text().strip()
        self.evidence_table.setRowCount(0)
        self.missing_shots_label.setText("")
        self.refresh_indexed_photos(show_empty=False)
        if not audit_id:
            self.result_panel.show_text("Enter a Related Audit ID to review photo evidence coverage.")
            return
        coverage = evidence_coverage_for_audit(self.config.project_root, audit_id)
        if coverage is None:
            self.result_panel.show_text(f"No audit row found for {audit_id}. You can still create an intake folder for phone photos.")
            return
        self.evidence_table.setRowCount(len(coverage.statuses))
        for row_index, status in enumerate(coverage.statuses):
            values = [
                status.label,
                "Yes" if status.applies else "No",
                "Yes" if status.required else "No",
                "Yes" if status.present else "No",
                str(status.photo_count),
                status.status,
                status.warning,
            ]
            for column, value in enumerate(values):
                self.evidence_table.setItem(row_index, column, QTableWidgetItem(value))
        missing = [status.label for status in coverage.statuses if status.required and not status.present]
        if missing:
            self.missing_shots_label.setText("Missing shot types: " + ", ".join(missing))
        else:
            self.missing_shots_label.setText("Missing shot types: none")
        self.result_panel.show_text(
            f"Evidence coverage for {coverage.audit_id}: "
            f"{coverage.complete_count} complete, {coverage.missing_required_count} required missing."
        )

    def refresh_indexed_photos(self, show_empty: bool = True) -> None:
        audit_id = self.audit_id_edit.text().strip()
        self.indexed_photos_table.setRowCount(0)
        if not audit_id:
            if show_empty:
                self.result_panel.show_text("Enter a Related Audit ID to review indexed photos.")
            return
        rows = indexed_photos_for_audit(self.config.project_root, audit_id)
        self.indexed_photos_table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            linked_field = self._linked_field_from_notes(str(row.get("Notes") or ""))
            path = resolve_indexed_photo_path(self.config.project_root, row)
            values = [
                str(row.get("Photo ID") or ""),
                str(row.get("EOAT Area Shown") or ""),
                str(row.get("Photo Filename") or ""),
                str(path),
                linked_field,
            ]
            for column, value in enumerate(values):
                self.indexed_photos_table.setItem(row_index, column, QTableWidgetItem(value))
        if show_empty:
            self.result_panel.show_text(f"Indexed photos for {audit_id}: {len(rows)}")

    def open_selected_indexed_photo(self) -> None:
        row_index = self.indexed_photos_table.currentRow()
        if row_index < 0:
            self.result_panel.show_text("Select an indexed photo first.")
            return
        path_item = self.indexed_photos_table.item(row_index, 3)
        if path_item is None:
            self.result_panel.show_text("Selected photo has no path.")
            return
        result = open_path(path_item.text())
        if not result.success:
            self.result_panel.show_result(result)

    def link_selected_photo_to_field(self) -> None:
        row_index = self.indexed_photos_table.currentRow()
        if row_index < 0:
            self.result_panel.show_text("Select an indexed photo first.")
            return
        photo_item = self.indexed_photos_table.item(row_index, 0)
        photo_id = photo_item.text().strip() if photo_item is not None else ""
        audit_field = self.audit_field_link_edit.text().strip()
        if not audit_field:
            self.result_panel.show_text("Enter an audit field to link this photo to.")
            return
        run_tool_background(
            self.result_panel,
            "photo_evidence_link_field",
            "Photo Evidence Field Link",
            lambda: link_photo_to_audit_field(self.config.project_root, photo_id, audit_field),
            self._field_link_finished,
            modifies_files=True,
            workbook_lock=True,
        )

    def _field_link_finished(self, result) -> None:
        if result.success:
            self.refresh_indexed_photos(show_empty=False)
            self.refresh_evidence_coverage()

    def _notes_with_field_link(self, notes: str, audit_field: str) -> str:
        audit_field = audit_field.strip()
        if not audit_field:
            return notes
        link_note = f"Linked audit field: {audit_field}"
        if link_note in notes:
            return notes
        return "\n".join(part for part in (notes, link_note) if part)

    def _linked_field_from_notes(self, notes: str) -> str:
        for line in notes.splitlines():
            if line.casefold().startswith("linked audit field:"):
                return line.split(":", 1)[1].strip()
        return ""

    def create_audit_intake_folder(self) -> None:
        audit_id = self.audit_id_edit.text().strip()
        result = create_audit_photo_intake_folder(self.config.project_root, audit_id)
        self.result_panel.show_result(result)

    def export_audit_photo_checklist(self) -> None:
        audit_id = self.audit_id_edit.text().strip()
        result = export_photo_checklist(self.config.project_root, audit_id)
        self.result_panel.show_result(result)

    def copy_audit_intake_path(self) -> None:
        audit_id = self.audit_id_edit.text().strip()
        if not audit_id:
            self.result_panel.show_text("Enter a Related Audit ID before copying the intake path.")
            return
        path = audit_photo_intake_folder(self.config.project_root, audit_id)
        app = QApplication.instance() if QApplication is not None else None
        if app is None:
            self.result_panel.show_text(str(path))
            return
        app.clipboard().setText(str(path))
        self.result_panel.show_text(f"Copied intake path:\n{path}")

    def open_audit_intake_folder(self) -> None:
        audit_id = self.audit_id_edit.text().strip()
        if not audit_id:
            self.result_panel.show_text("Enter a Related Audit ID before opening the intake folder.")
            return
        result = open_path(audit_photo_intake_folder(self.config.project_root, audit_id))
        if not result.success:
            self.result_panel.show_result(result)
