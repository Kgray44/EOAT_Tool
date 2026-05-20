from __future__ import annotations

from datetime import date

try:
    from PySide6.QtWidgets import (
        QCheckBox,
        QComboBox,
        QFormLayout,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QListWidget,
        QListWidgetItem,
        QPushButton,
        QTextEdit,
        QVBoxLayout,
        QWidget,
    )
except ImportError:  # pragma: no cover
    QCheckBox = QComboBox = QFormLayout = QHBoxLayout = QLabel = QLineEdit = QListWidget = QListWidgetItem = QPushButton = QTextEdit = QVBoxLayout = QWidget = None

from app.widgets.tool_run_panel import ToolRunPanel
from app.page_tasks import run_tool_background
from core.openers import open_path
from core.paths import resolve_project_paths
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
                notes=data["notes"],
                copy_mode=self.copy_check.isChecked(),
            ),
            self._intake_finished,
            modifies_files=True,
            workbook_lock=True,
        )

    def _intake_finished(self, result) -> None:
        if result.success:
            self.refresh_incoming()

    def open_incoming(self) -> None:
        result = open_path(resolve_project_paths(self.config.project_root).incoming_photos)
        if not result.success:
            self.result_panel.show_result(result)

    def open_cell_photos(self) -> None:
        result = open_path(resolve_project_paths(self.config.project_root).cell_photos)
        if not result.success:
            self.result_panel.show_result(result)
