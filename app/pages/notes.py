from __future__ import annotations

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import (
        QComboBox,
        QDialog,
        QDialogButtonBox,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QListWidget,
        QListWidgetItem,
        QMessageBox,
        QPushButton,
        QSplitter,
        QTableWidget,
        QTableWidgetItem,
        QVBoxLayout,
        QWidget,
    )
except ImportError:  # pragma: no cover
    Qt = None
    QComboBox = QDialog = QDialogButtonBox = QHBoxLayout = QLabel = QLineEdit = QListWidget = QListWidgetItem = (
        QMessageBox
    ) = QPushButton = QSplitter = QTableWidget = QTableWidgetItem = QVBoxLayout = QWidget = None

from app.widgets.annotation_target_navigator import AnnotationTargetNavigator
from app.widgets.annotation_target_picker import AnnotationTargetPicker
from app.widgets.note_editor import NoteEditor
from app.widgets.tag_picker import TagPicker
from core.annotations.service import AnnotationService


class NotesPage(QWidget):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.service = AnnotationService(config.project_root)
        self.selected_note_id: str | None = None

        layout = QVBoxLayout(self)
        heading = QLabel("Notes")
        heading.setStyleSheet("font-size: 18pt; font-weight: 600;")
        layout.addWidget(heading)

        filter_row = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search notes, targets, machines, audit IDs, and tags...")
        self.search_edit.textChanged.connect(self.refresh_notes)
        self.importance_filter = QComboBox()
        self.importance_filter.addItems(["All", "Low", "Neutral", "Important", "Critical"])
        self.importance_filter.currentTextChanged.connect(self.refresh_notes)
        self.status_filter = QComboBox()
        self.status_filter.addItems(["All", "Open", "Resolved", "Archived"])
        self.status_filter.currentTextChanged.connect(self.refresh_notes)
        self.sort_combo = QComboBox()
        self.sort_combo.addItems(
            [
                "Updated Date",
                "Created Date",
                "Subject Alphabetical",
                "Importance",
                "Status",
                "Collection",
                "Note Type",
                "Follow-Up Date",
            ]
        )
        self.sort_combo.currentTextChanged.connect(self.refresh_notes)
        new_button = QPushButton("+ New Note")
        new_button.clicked.connect(self.new_note)
        export_md = QPushButton("Export Markdown")
        export_md.clicked.connect(self.export_markdown)
        export_xlsx = QPushButton("Export Excel")
        export_xlsx.clicked.connect(self.export_excel)
        for widget in [
            self.search_edit,
            self.importance_filter,
            self.status_filter,
            self.sort_combo,
            new_button,
            export_md,
            export_xlsx,
        ]:
            filter_row.addWidget(widget)
        layout.addLayout(filter_row)

        splitter = QSplitter()
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(
            ["Subject", "Importance", "Status", "Collection", "Type", "Updated", "Links"]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.itemSelectionChanged.connect(self.load_selected_note)
        splitter.addWidget(self.table)

        editor_panel = QWidget()
        editor_layout = QVBoxLayout(editor_panel)
        self.editor = NoteEditor()
        self._configure_add_field_menu()
        editor_layout.addWidget(self.editor)
        self.target_picker = AnnotationTargetPicker()
        self.target_picker.hide()
        editor_layout.addWidget(self.target_picker)
        self.tag_picker = TagPicker(self.service)
        self.tag_picker.hide()
        editor_layout.addWidget(self.tag_picker)
        action_row = QHBoxLayout()
        save_button = QPushButton("Save Note")
        save_button.clicked.connect(self.save_note)
        archive_button = QPushButton("Archive Note")
        archive_button.clicked.connect(self.archive_note)
        self.go_to_target_button = QPushButton("Go to Target")
        self.go_to_target_button.clicked.connect(self.go_to_target)
        action_row.addWidget(save_button)
        action_row.addWidget(archive_button)
        action_row.addWidget(self.go_to_target_button)
        action_row.addStretch(1)
        editor_layout.addLayout(action_row)
        splitter.addWidget(editor_panel)
        splitter.setSizes([520, 540])
        layout.addWidget(splitter, stretch=1)

        self.status_label = QLabel()
        self.status_label.setObjectName("MutedText")
        layout.addWidget(self.status_label)
        self.refresh_notes()
        self._update_go_to_target_state()

    def refresh(self) -> None:
        self.tag_picker.refresh()
        self.refresh_notes()

    def _configure_add_field_menu(self) -> None:
        self.editor.add_field_button.clicked.connect(self._show_add_field_dialog)

    def _show_add_field_dialog(self) -> None:
        descriptions = {
            "status": "Open, resolved, or archived state.",
            "collection": "Folder or project grouping.",
            "note_type": "Question, decision, issue, observation, or local category.",
            "follow_up_date": "Date used for sorting and Open Items follow-up counts.",
            "linked_audit_id": "Link this note to a saved audit ID.",
            "linked_machine": "Link this note to a machine or press number.",
            "linked_eoat_tool": "Link this note to an EOAT/tool number or identifier.",
            "linked_audit_field": "Link this note to a specific audit field/header.",
            "linked_compatibility_entry": "Link this note to a compatibility relationship or entry.",
            "attachment": "Local photo, folder, or document path reference.",
            "linked_workbook_warning": "Link this note to a workbook health warning.",
            "linked_pilot_candidate": "Link this note to pilot-candidate evidence.",
            "target": "General target picker for audits, fields, machines, photos, warnings, and project items.",
            "tags": "Related visual tags stored in the annotation database.",
            "created_by": "Optional author/source note.",
            "due_review_date": "Optional review date separate from follow-up date.",
            "priority_reason": "Why this note matters.",
            "source_evidence": "Evidence or source reference.",
            "assigned_to": "Owner for follow-up or resolution.",
            "resolution_notes": "Closure notes or final decision.",
            "related_report": "Report path or report name.",
            "related_pm_checklist_item": "PM checklist item reference.",
            "related_fmea_item": "FMEA item reference.",
            "related_issue": "Issue analysis category or item.",
            "related_standard_guideline": "Standard, guideline, or work instruction reference.",
            "related_spare_part_bom_item": "BOM/spare part reference.",
        }
        dialog = QDialog(self)
        dialog.setWindowTitle("Add Note Field")
        dialog.resize(760, 580)
        layout = QVBoxLayout(dialog)
        search = QLineEdit()
        search.setPlaceholderText("Search optional fields...")
        layout.addWidget(search)
        list_widget = QListWidget()
        layout.addWidget(list_widget)

        def populate(filter_text: str = "") -> None:
            list_widget.clear()
            needle = filter_text.casefold().strip()
            for label, key in self.editor.OPTIONAL_FIELDS:
                text = f"{label} - {descriptions.get(key, '')}"
                if needle and needle not in text.casefold():
                    continue
                item = QListWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, key)
                list_widget.addItem(item)
            if list_widget.count():
                list_widget.setCurrentRow(0)

        populate()
        search.textChanged.connect(populate)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted and list_widget.currentItem() is not None:
            self._show_optional(str(list_widget.currentItem().data(Qt.ItemDataRole.UserRole)))

    def _show_optional(self, key: str) -> None:
        if key == "target":
            self.target_picker.show()
        elif key == "tags":
            self.tag_picker.show()
        else:
            self.editor.show_optional_field(key)

    def refresh_notes(self) -> None:
        self.notes = self.service.search_notes(
            self.search_edit.text(),
            importance=self.importance_filter.currentText(),
            status=self.status_filter.currentText(),
            sort_by=self.sort_combo.currentText(),
        )
        self.table.setRowCount(len(self.notes))
        for row_index, note in enumerate(self.notes):
            links = []
            if note.get("targets"):
                links.append(f"{len(note['targets'])} target(s)")
            if note.get("tags"):
                links.append(f"{len(note['tags'])} tag(s)")
            values = [
                note.get("subject", ""),
                note.get("importance", ""),
                note.get("status", ""),
                note.get("collection", ""),
                note.get("note_type", ""),
                note.get("updated_at", ""),
                ", ".join(links),
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value or ""))
                if col == 0:
                    item.setData(Qt.ItemDataRole.UserRole, note["id"])
                self.table.setItem(row_index, col, item)
        self.table.resizeColumnsToContents()
        self.status_label.setText(f"{len(self.notes)} note(s)")
        self._update_go_to_target_state()

    def new_note(self) -> None:
        self.selected_note_id = None
        self.editor.clear()
        self.target_picker.hide()
        self.tag_picker.hide()
        self.status_label.setText("New note ready.")

    def load_selected_note(self) -> None:
        selected = self.table.selectedItems()
        if not selected:
            return
        row = selected[0].row()
        item = self.table.item(row, 0)
        note_id = item.data(Qt.ItemDataRole.UserRole) if item else None
        if not note_id:
            return
        self.selected_note_id = str(note_id)
        note = next((item for item in self.notes if item["id"] == self.selected_note_id), None)
        if note:
            self.editor.set_values(note)
            self.status_label.setText(f"Loaded note: {note['subject']}")
        self._update_go_to_target_state()

    def save_note(self) -> None:
        values = self.editor.values()
        try:
            target_ids = []
            if self.target_picker.isVisible():
                kwargs = self.target_picker.target_kwargs()
                if any(
                    kwargs.get(key) for key in ["audit_id", "machine_id", "field_key", "object_ref", "target_label"]
                ):
                    target_ids.append(self.service.create_or_get_target(**kwargs).id)
            target_ids.extend(self._targets_from_optional_values(values))
            tag_ids = (
                [self.tag_picker.current_tag_id()]
                if self.tag_picker.isVisible() and self.tag_picker.current_tag_id()
                else []
            )
            attachment = values.pop("attachment", None)
            metadata_keys = {
                "created_by",
                "linked_audit_id",
                "linked_machine",
                "linked_eoat_tool",
                "linked_audit_field",
                "linked_compatibility_entry",
                "linked_workbook_warning",
                "linked_pilot_candidate",
                "due_review_date",
                "priority_reason",
                "source_evidence",
                "assigned_to",
                "resolution_notes",
                "related_report",
                "related_pm_checklist_item",
                "related_fmea_item",
                "related_issue",
                "related_standard_guideline",
                "related_spare_part_bom_item",
            }
            for key in metadata_keys:
                values.pop(key, None)
            if self.selected_note_id:
                note = self.service.update_note(self.selected_note_id, **values)
                for target_id in target_ids:
                    self.service.link_note_to_target(note.id, target_id)
                for tag_id in tag_ids:
                    self.service.link_note_to_tag(note.id, tag_id)
                if attachment:
                    self.service.attach_file(note_id=note.id, file_path=attachment)
            else:
                note = self.service.create_note(
                    str(values["subject"]),
                    str(values.get("body_markdown") or ""),
                    str(values.get("importance") or "Neutral"),
                    status=values.get("status"),
                    collection=values.get("collection"),
                    note_type=values.get("note_type"),
                    follow_up_date=values.get("follow_up_date"),
                    target_ids=target_ids,
                    tag_ids=[tag_id for tag_id in tag_ids if tag_id],
                    attachment_paths=[attachment] if attachment else None,
                )
                self.selected_note_id = note.id
            self.refresh_notes()
            self.status_label.setText(f"Saved note: {note.subject}")
        except Exception as exc:
            QMessageBox.warning(self, "Save Note", f"Could not save note: {exc}")

    def _targets_from_optional_values(self, values: dict[str, object]) -> list[str]:
        target_ids: list[str] = []
        audit_id = str(values.get("linked_audit_id") or "").strip()
        machine = str(values.get("linked_machine") or "").strip()
        audit_field = str(values.get("linked_audit_field") or "").strip()
        if audit_id:
            target_ids.append(self.service.create_or_get_target("audit", audit_id=audit_id, target_label=audit_id).id)
        if machine:
            target_ids.append(
                self.service.create_or_get_target("machine", machine_id=machine, target_label=f"Machine {machine}").id
            )
        if audit_field:
            target_ids.append(
                self.service.create_or_get_target(
                    "audit_field",
                    audit_id=audit_id,
                    machine_id=machine,
                    field_key=audit_field,
                    field_label=audit_field,
                    sheet_name="EOAT Inventory",
                    header_name=audit_field,
                ).id
            )
        mappings = [
            ("linked_eoat_tool", "project_item", "EOAT / Tool"),
            ("linked_compatibility_entry", "compatibility_entry", "Fit Check Entry"),
            ("linked_workbook_warning", "workbook_warning", "Workbook Warning"),
            ("linked_pilot_candidate", "pilot_candidate", "Pilot Candidate"),
            ("related_report", "project_item", "Report"),
            ("related_pm_checklist_item", "project_item", "PM Checklist Item"),
            ("related_fmea_item", "project_item", "FMEA Item"),
            ("related_issue", "project_item", "Issue"),
            ("related_standard_guideline", "project_item", "Standard / Guideline"),
            ("related_spare_part_bom_item", "project_item", "BOM / Spare Part"),
        ]
        for key, target_type, label_prefix in mappings:
            value = str(values.get(key) or "").strip()
            if value:
                target_ids.append(
                    self.service.create_or_get_target(
                        target_type, target_label=f"{label_prefix}: {value}", object_ref=value
                    ).id
                )
        return target_ids

    def archive_note(self) -> None:
        if not self.selected_note_id:
            return
        answer = QMessageBox.question(
            self, "Archive Note", "Archive this note? It can remain in the database for audit history."
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.service.archive_note(self.selected_note_id)
        self.new_note()
        self.refresh_notes()

    def selected_note(self) -> dict[str, object] | None:
        if not self.selected_note_id:
            return None
        return next((note for note in self.notes if note["id"] == self.selected_note_id), None)

    def go_to_target(self) -> None:
        note = self.selected_note()
        targets = list(note.get("targets") or []) if note else []
        if not targets:
            self.status_label.setText("This note does not have a linked target to open.")
            return
        AnnotationTargetNavigator(self).open_targets(targets, title="Select Target for Note")

    def select_note(self, note_id: str) -> None:
        self.refresh_notes()
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and str(item.data(Qt.ItemDataRole.UserRole)) == str(note_id):
                self.table.selectRow(row)
                self.table.scrollToItem(item)
                self.selected_note_id = str(note_id)
                self.load_selected_note()
                break
        self._update_go_to_target_state()

    def _update_go_to_target_state(self) -> None:
        note = self.selected_note()
        self.go_to_target_button.setEnabled(bool(note and note.get("targets")))

    def export_markdown(self) -> None:
        path = self.service.export_notes_markdown(self.notes)
        self.status_label.setText(f"Exported Markdown: {path}")

    def export_excel(self) -> None:
        path = self.service.export_notes_excel(self.notes)
        self.status_label.setText(f"Exported Excel: {path}")
