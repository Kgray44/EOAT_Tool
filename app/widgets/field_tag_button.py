from __future__ import annotations

from collections.abc import Callable
from typing import Any

try:
    from PySide6.QtCore import QSize, Qt
    from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
    from PySide6.QtWidgets import (
        QComboBox,
        QDialog,
        QDialogButtonBox,
        QFormLayout,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QListWidget,
        QListWidgetItem,
        QMessageBox,
        QPushButton,
        QTextEdit,
        QToolButton,
        QVBoxLayout,
        QWidget,
    )
except ImportError:  # pragma: no cover
    QSize = Qt = QColor = QIcon = QPainter = QPen = QPixmap = None
    QComboBox = QDialog = QDialogButtonBox = QFormLayout = QHBoxLayout = QLabel = QLineEdit = QListWidget = (
        QListWidgetItem
    ) = QMessageBox = QPushButton = QTextEdit = QToolButton = QVBoxLayout = QWidget = None

from core.annotations.service import AnnotationService
from core.annotations.tag_colors import TAG_COLOR_PALETTE


def _flag_icon(color: str) -> QIcon:
    pixmap = QPixmap(16, 16)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color))
    pen.setWidth(2)
    painter.setPen(pen)
    painter.drawLine(4, 3, 4, 14)
    painter.drawLine(4, 3, 12, 5)
    painter.drawLine(12, 5, 4, 8)
    painter.end()
    return QIcon(pixmap)


class FieldTagButton(QToolButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setToolTip("Add tag or note")
        self.setAutoRaise(True)
        self.setFixedWidth(28)
        self.setIconSize(QSize(16, 16))
        self.setProperty("annotation_icon", "flag")
        self.set_annotation_state([], [])

    def set_tag_state(self, tag_names: list[str]) -> None:
        self.set_annotation_state(tag_names, [])

    def set_annotation_state(self, tag_names: list[str], note_subjects: list[str]) -> None:
        active = bool(tag_names or note_subjects)
        self.setProperty("annotation_active", active)
        self.setIcon(_flag_icon("#2563eb" if active else "#6b7280"))
        if active:
            count_parts = []
            if tag_names:
                count_parts.append(f"{len(tag_names)} tag" + ("" if len(tag_names) == 1 else "s"))
            if note_subjects:
                count_parts.append(f"{len(note_subjects)} note" + ("" if len(note_subjects) == 1 else "s"))
            parts = []
            if count_parts:
                parts.append(", ".join(count_parts))
            if tag_names:
                parts.append("Tags: " + ", ".join(tag_names))
            if note_subjects:
                parts.append("Notes: " + ", ".join(note_subjects[:3]))
            self.setToolTip("\n".join(parts))
            self.setStyleSheet(
                """
                QToolButton { border: 1px solid #93c5fd; background: #eff6ff; border-radius: 4px; }
                QToolButton:hover { border-color: #60a5fa; background: #dbeafe; }
                QToolButton:pressed { border-color: #2563eb; background: #bfdbfe; padding-top: 1px; }
                """
            )
        else:
            self.setToolTip("Add tag or note")
            self.setStyleSheet(
                """
                QToolButton { border: 1px solid transparent; background: transparent; border-radius: 4px; }
                QToolButton:hover { border-color: #d1d5db; background: #f3f4f6; }
                QToolButton:pressed { border-color: #9ca3af; background: #e5e7eb; padding-top: 1px; }
                """
            )


class FieldNoteDialog(QDialog):
    def __init__(self, service: AnnotationService, target, *, field_label: str, parent=None):
        super().__init__(parent)
        self.service = service
        self.target = target
        self.created_note_id: str | None = None
        self.note_payload: dict[str, object] | None = None
        self.setWindowTitle(f"Create Note: {field_label}")
        self.resize(560, 460)

        layout = QVBoxLayout(self)
        target_label = QLabel(f"Linked target: {target.target_label or field_label}")
        target_label.setWordWrap(True)
        layout.addWidget(target_label)

        form = QFormLayout()
        self.subject_edit = QLineEdit(f"Note for {field_label}")
        self.importance_combo = QComboBox()
        self.importance_combo.addItems(["Low", "Neutral", "Important", "Critical"])
        self.importance_combo.setCurrentText("Neutral")
        self.status_combo = QComboBox()
        self.status_combo.addItems(["", "Open", "Resolved", "Archived"])
        self.status_combo.setCurrentText("Open")
        self.body_edit = QTextEdit()
        self.body_edit.setPlaceholderText("Write the field note. Markdown/plain text is saved safely.")
        form.addRow("Subject", self.subject_edit)
        form.addRow("Importance", self.importance_combo)
        form.addRow("Status", self.status_combo)
        form.addRow("Body", self.body_edit)
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.save_note)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def save_note(self) -> None:
        subject = self.subject_edit.text().strip()
        if not subject:
            QMessageBox.information(self, "Create Note", "Subject is required.")
            return
        self.note_payload = {
            "subject": subject,
            "body_markdown": self.body_edit.toPlainText(),
            "importance": self.importance_combo.currentText(),
            "status": self.status_combo.currentText().strip() or None,
            "target_ids": [self.target.id],
        }
        self.accept()


class FieldTagDialog(QDialog):
    TAG_ID_ROLE = 256
    ASSIGNMENT_ID_ROLE = 257
    STAGED_INDEX_ROLE = 258

    def __init__(
        self,
        service: AnnotationService,
        target,
        *,
        field_label: str,
        current_value: str,
        tag_photo_callback: Callable[[Any], bool] | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.service = service
        self.target = target
        self.field_label = field_label
        self._tag_photo_callback = tag_photo_callback
        self.created_note_ids: list[str] = []
        self._available_tags = []
        self._staged_assignments: list[dict[str, object]] = []
        self._deleted_assignments: list[dict[str, object]] = []
        self._staged_notes: list[dict[str, object]] = []
        self._staged_note_links: list[str] = []
        self._pending_tag_changes = False
        self._pending_note_changes = False
        self._editor_mode = "add"
        self._editing_index: int | None = None
        self.setWindowTitle(f"Tag Field: {field_label}")
        self.resize(620, 620)

        layout = QVBoxLayout(self)
        header = QLabel(
            f"{field_label}\nAudit ID: {target.audit_id or 'Unsaved'}\nCurrent value: {current_value or '(blank)'}"
        )
        header.setWordWrap(True)
        layout.addWidget(header)

        self.existing_list = QListWidget()
        self.existing_list.itemDoubleClicked.connect(lambda _item: self._go_to_selected_tag())
        layout.addWidget(QLabel("Existing Tags"))
        layout.addWidget(self.existing_list)
        self.empty_tags_label = QLabel("No tags on this field yet.")
        self.empty_tags_label.setObjectName("MutedText")
        layout.addWidget(self.empty_tags_label)

        action_row = QHBoxLayout()
        self.show_add_tag_button = QPushButton("Add Tag")
        self.show_add_tag_button.clicked.connect(self.show_add_tag_controls)
        self.edit_tag_button = QPushButton("Edit Tag")
        self.edit_tag_button.clicked.connect(self.show_edit_tag_controls)
        self.delete_tag_button = QPushButton("Delete Tag")
        self.delete_tag_button.clicked.connect(self.remove_selected_tag)
        self.go_to_tag_button = QPushButton("Go to Tag")
        self.go_to_tag_button.clicked.connect(self._go_to_selected_tag)
        action_row.addWidget(self.show_add_tag_button)
        action_row.addWidget(self.edit_tag_button)
        action_row.addWidget(self.delete_tag_button)
        action_row.addWidget(self.go_to_tag_button)
        action_row.addStretch(1)
        layout.addLayout(action_row)

        self.add_tag_panel = QWidget()
        form = QFormLayout(self.add_tag_panel)
        self.tag_combo = QComboBox()
        self.tag_combo.setEditable(False)
        self.tag_combo.currentIndexChanged.connect(self._update_color_preview)
        self.color_preview_label = QLabel()
        self.color_preview_label.setObjectName("MutedText")
        self.comment_edit = QTextEdit()
        self.comment_edit.setFixedHeight(70)
        form.addRow("Tag", self.tag_combo)
        form.addRow("Color", self.color_preview_label)
        form.addRow("Comment", self.comment_edit)
        add_controls_row = QHBoxLayout()
        self.confirm_add_tag_button = QPushButton("Add")
        self.confirm_add_tag_button.clicked.connect(self.save_tag_editor)
        self.cancel_add_tag_button = QPushButton("Cancel")
        self.cancel_add_tag_button.clicked.connect(self.hide_add_tag_controls)
        add_controls_row.addStretch(1)
        add_controls_row.addWidget(self.confirm_add_tag_button)
        add_controls_row.addWidget(self.cancel_add_tag_button)
        form.addRow("", add_controls_row)
        self.add_tag_panel.hide()
        layout.addWidget(self.add_tag_panel)

        note_button = QPushButton("Create Note About This Field")
        note_button.clicked.connect(self.create_note)
        self.tag_photo_button = QPushButton("Attach Photo to This Field")
        self.tag_photo_button.setToolTip("Attach a photo to this exact audit field.")
        self.tag_photo_button.clicked.connect(self.tag_photo)
        self.link_note_combo = QComboBox()
        link_note_button = QPushButton("Link Existing Note")
        link_note_button.clicked.connect(self.link_existing_note)
        layout.addWidget(note_button)
        layout.addWidget(self.tag_photo_button)
        link_row = QHBoxLayout()
        link_row.addWidget(self.link_note_combo, stretch=1)
        link_row.addWidget(link_note_button)
        layout.addLayout(link_row)

        self.status_label = QLabel()
        self.status_label.setObjectName("MutedText")
        layout.addWidget(self.status_label)

        footer = QHBoxLayout()
        footer.addStretch(1)
        self.primary_button = QPushButton("Done")
        self.primary_button.clicked.connect(self.accept)
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        footer.addWidget(self.primary_button)
        footer.addWidget(cancel_button)
        layout.addLayout(footer)
        self.refresh()

    def refresh(self) -> None:
        self._available_tags = self.service.list_tags()
        self._staged_assignments = [
            self._assignment_from_service_tag(tag) for tag in self.service.get_tags_for_target(self.target.id)
        ]
        self._deleted_assignments = []
        self._staged_notes = []
        self._staged_note_links = []
        self._pending_tag_changes = False
        self._pending_note_changes = False
        self._populate_tag_combo()
        self._populate_link_note_combo()
        self._render_existing_tags()
        self.hide_add_tag_controls()
        self._update_primary_button()

    def _populate_tag_combo(self) -> None:
        current_tag_id = self.tag_combo.currentData()
        self.tag_combo.blockSignals(True)
        self.tag_combo.clear()
        for tag in self._available_tags:
            self.tag_combo.addItem(tag.name, tag.id)
        if current_tag_id:
            index = self.tag_combo.findData(current_tag_id)
            if index >= 0:
                self.tag_combo.setCurrentIndex(index)
        self.tag_combo.blockSignals(False)
        self._update_color_preview()

    def _populate_link_note_combo(self) -> None:
        self.link_note_combo.clear()
        self.link_note_combo.addItem("", None)
        for note in self.service.search_notes(sort_by="updated"):
            self.link_note_combo.addItem(str(note["subject"]), note["id"])

    def _assignment_from_service_tag(self, tag: dict[str, object]) -> dict[str, object]:
        return {
            "assignment_id": tag.get("assignment_id"),
            "tag_id": tag.get("id"),
            "original_tag_id": tag.get("id"),
            "name": tag.get("name"),
            "color_key": tag.get("color_key"),
            "comment": str(tag.get("comment") or ""),
            "original_comment": str(tag.get("comment") or ""),
            "is_new": False,
        }

    def _render_existing_tags(self) -> None:
        self.existing_list.clear()
        self.empty_tags_label.setVisible(not self._staged_assignments)
        for index, assignment in enumerate(self._staged_assignments):
            item = QListWidgetItem(self._assignment_display(assignment))
            item.setData(self.TAG_ID_ROLE, assignment.get("tag_id"))
            item.setData(self.ASSIGNMENT_ID_ROLE, assignment.get("assignment_id"))
            item.setData(self.STAGED_INDEX_ROLE, index)
            item.setToolTip(self._assignment_tooltip(assignment))
            color_key = str(assignment.get("color_key") or "yellow")
            color = TAG_COLOR_PALETTE.get(color_key)
            if color is not None:
                item.setBackground(QColor(color.ui_hex))
            self.existing_list.addItem(item)
        self.delete_tag_button.setEnabled(bool(self._staged_assignments))
        self.go_to_tag_button.setEnabled(bool(self._staged_assignments))
        self.edit_tag_button.setEnabled(bool(self._staged_assignments))

    def _assignment_display(self, assignment: dict[str, object]) -> str:
        comment = str(assignment.get("comment") or "").strip() or "No comment"
        return f"{assignment.get('name') or 'Tag'} | {comment}"

    def _assignment_tooltip(self, assignment: dict[str, object]) -> str:
        color_key = str(assignment.get("color_key") or "")
        color_label = TAG_COLOR_PALETTE[color_key].label if color_key in TAG_COLOR_PALETTE else color_key
        comment = str(assignment.get("comment") or "").strip() or "No comment"
        target_label = self.target.target_label or self.target.field_label or self.target.field_key or self.field_label
        return f"Tag: {assignment.get('name')}\nColor: {color_label}\nComment: {comment}\nTarget: {target_label}"

    def show_add_tag_controls(self) -> None:
        self._editor_mode = "add"
        self._editing_index = None
        self.confirm_add_tag_button.setText("Add")
        self.add_tag_panel.show()
        self.comment_edit.clear()
        self._update_color_preview()
        self.status_label.setText("Choose a tag and optional comment, then Add.")

    def show_edit_tag_controls(self) -> None:
        item = self.existing_list.currentItem()
        if item is None:
            return
        index = int(item.data(self.STAGED_INDEX_ROLE))
        if index < 0 or index >= len(self._staged_assignments):
            return
        assignment = self._staged_assignments[index]
        self._editor_mode = "edit"
        self._editing_index = index
        tag_index = self.tag_combo.findData(assignment.get("tag_id"))
        if tag_index >= 0:
            self.tag_combo.setCurrentIndex(tag_index)
        self.comment_edit.setPlainText(str(assignment.get("comment") or ""))
        self.confirm_add_tag_button.setText("Save Edit")
        self.add_tag_panel.show()
        self._update_color_preview()
        self.status_label.setText("Edit the selected field tag assignment.")

    def hide_add_tag_controls(self) -> None:
        self._editor_mode = "add"
        self._editing_index = None
        self.confirm_add_tag_button.setText("Add")
        self.add_tag_panel.hide()

    def add_tag(self) -> None:
        self._editor_mode = "add"
        self._editing_index = None
        self.save_tag_editor()

    def save_tag_editor(self) -> None:
        tag_id = self.tag_combo.currentData()
        if tag_id:
            tag = self.service.get_tag(str(tag_id))
        else:
            QMessageBox.information(self, "Tag Field", "Choose a tag.")
            return
        comment = self.comment_edit.toPlainText().strip()
        if self._editor_mode == "edit" and self._editing_index is not None:
            assignment = self._staged_assignments[self._editing_index]
            duplicate = next(
                (
                    item
                    for index, item in enumerate(self._staged_assignments)
                    if index != self._editing_index and item.get("tag_id") == tag.id
                ),
                None,
            )
            if duplicate is not None:
                duplicate["comment"] = comment
                if assignment.get("assignment_id"):
                    self._deleted_assignments.append(assignment)
                self._staged_assignments.pop(self._editing_index)
            else:
                assignment["tag_id"] = tag.id
                assignment["name"] = tag.name
                assignment["color_key"] = tag.color_key
                assignment["comment"] = comment
        else:
            existing = next((item for item in self._staged_assignments if item.get("tag_id") == tag.id), None)
            if existing is not None:
                existing["comment"] = comment
                existing["color_key"] = tag.color_key
                existing["name"] = tag.name
            else:
                self._staged_assignments.append(
                    {
                        "assignment_id": None,
                        "tag_id": tag.id,
                        "original_tag_id": None,
                        "name": tag.name,
                        "color_key": tag.color_key,
                        "comment": comment,
                        "original_comment": "",
                        "is_new": True,
                    }
                )
        self._pending_tag_changes = True
        self.hide_add_tag_controls()
        self._render_existing_tags()
        self._update_primary_button()
        self.status_label.setText(f"Staged tag assignment: {tag.name}")

    def remove_selected_tag(self) -> None:
        item = self.existing_list.currentItem()
        if item is None:
            return
        if not self._confirm_remove_tag():
            return
        index = int(item.data(self.STAGED_INDEX_ROLE))
        assignment = self._staged_assignments.pop(index)
        if assignment.get("assignment_id"):
            self._deleted_assignments.append(assignment)
        self._pending_tag_changes = True
        self._render_existing_tags()
        self._update_primary_button()
        self.status_label.setText("Staged tag removal.")

    def create_note(self) -> None:
        field_label = self.target.field_label or self.target.field_key or "Audit field"
        dialog = FieldNoteDialog(self.service, self.target, field_label=field_label, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            if dialog.note_payload:
                self._staged_notes.append(dialog.note_payload)
                self._pending_note_changes = True
                self.status_label.setText("Staged field note. Press Done to keep it, or Cancel to discard it.")
                self._update_primary_button()

    def link_existing_note(self) -> None:
        note_id = self.link_note_combo.currentData()
        if not note_id:
            return
        note_id = str(note_id)
        if note_id not in self._staged_note_links:
            self._staged_note_links.append(note_id)
        self._pending_note_changes = True
        self.status_label.setText("Staged existing note link. Press Done to keep it, or Cancel to discard it.")
        self._update_primary_button()

    def tag_photo(self) -> None:
        if self._tag_photo_callback is None:
            QMessageBox.information(self, "Attach Photo", "Photo linking is not available from this window.")
            return
        if self._has_pending_changes() and not self._confirm_tag_photo_navigation_with_pending_changes():
            return
        if self._tag_photo_callback(self.target):
            super().accept()

    def accept(self) -> None:
        if self.commit_changes():
            super().accept()

    def commit_changes(self) -> bool:
        try:
            for assignment in self._deleted_assignments:
                self.service.remove_tag_from_target(
                    str(assignment.get("original_tag_id") or assignment["tag_id"]), self.target.id, sync_workbook=False
                )
            for assignment in self._staged_assignments:
                comment = str(assignment.get("comment") or "")
                original_tag_id = str(assignment.get("original_tag_id") or "")
                current_tag_id = str(assignment["tag_id"])
                if original_tag_id and original_tag_id != current_tag_id:
                    self.service.remove_tag_from_target(original_tag_id, self.target.id, sync_workbook=False)
                    self.service.assign_tag_to_target(
                        current_tag_id, self.target.id, comment=comment, sync_workbook=False
                    )
                elif assignment.get("is_new") or comment != str(assignment.get("original_comment") or ""):
                    self.service.assign_tag_to_target(
                        str(assignment["tag_id"]), self.target.id, comment=comment, sync_workbook=False
                    )
            for payload in self._staged_notes:
                note = self.service.create_note(
                    str(payload["subject"]),
                    str(payload.get("body_markdown") or ""),
                    str(payload.get("importance") or "Neutral"),
                    status=payload.get("status"),
                    target_ids=[self.target.id],
                )
                self.created_note_ids.append(note.id)
            for note_id in self._staged_note_links:
                self.service.link_note_to_target(note_id, self.target.id)
            if self._pending_tag_changes:
                self.service.sync_target_colors_to_workbook(self.target.id)
        except Exception as exc:
            QMessageBox.warning(self, "Tag Field", f"Could not save field annotations: {exc}")
            return False
        self._pending_tag_changes = False
        self._pending_note_changes = False
        return True

    def _update_color_preview(self) -> None:
        tag_id = self.tag_combo.currentData()
        if not tag_id:
            self.color_preview_label.setText("Select a tag")
            self.color_preview_label.setStyleSheet("")
            return
        tag = self.service.get_tag(str(tag_id))
        color = TAG_COLOR_PALETTE[tag.color_key]
        self.color_preview_label.setText(color.label)
        self.color_preview_label.setStyleSheet(
            f"QLabel {{ padding: 4px 8px; border: 1px solid #cbd5e1; border-radius: 4px; background: {color.ui_hex}; color: #111827; }}"
        )

    def _update_primary_button(self) -> None:
        self.primary_button.setText("Save" if self._pending_tag_changes else "Done")

    def _has_pending_changes(self) -> bool:
        return self._pending_tag_changes or self._pending_note_changes

    def _confirm_remove_tag(self) -> bool:
        box = QMessageBox(self)
        box.setWindowTitle("Remove Tag")
        box.setText("Remove this tag from this field?")
        box.setInformativeText(
            "This will remove the selected tag assignment from this field. It will not delete the tag itself."
        )
        cancel_button = box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        remove_button = box.addButton("Remove Tag", QMessageBox.ButtonRole.DestructiveRole)
        box.setDefaultButton(cancel_button)
        box.exec()
        return box.clickedButton() == remove_button

    def _confirm_navigation_with_pending_changes(self) -> bool:
        if not self._has_pending_changes():
            return True
        box = QMessageBox(self)
        box.setWindowTitle("Open Tag")
        box.setText("You have unsaved field annotation changes.")
        box.setInformativeText("Save these changes before opening the Tags page, discard them, or stay here.")
        save_button = box.addButton("Save", QMessageBox.ButtonRole.AcceptRole)
        discard_button = box.addButton("Discard", QMessageBox.ButtonRole.DestructiveRole)
        cancel_button = box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(save_button)
        box.exec()
        clicked = box.clickedButton()
        if clicked == cancel_button:
            return False
        if clicked == save_button and not self.commit_changes():
            return False
        if clicked == discard_button:
            self.reject()
        return True

    def _confirm_tag_photo_navigation_with_pending_changes(self) -> bool:
        box = QMessageBox(self)
        box.setWindowTitle("Attach Photo")
        box.setText("You have unsaved field annotation changes.")
        box.setInformativeText("Save these changes before attaching a photo, discard them, or stay here.")
        save_button = box.addButton("Save", QMessageBox.ButtonRole.AcceptRole)
        discard_button = box.addButton("Discard", QMessageBox.ButtonRole.DestructiveRole)
        cancel_button = box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(save_button)
        box.exec()
        clicked = box.clickedButton()
        if clicked == cancel_button:
            return False
        if clicked == save_button and not self.commit_changes():
            return False
        if clicked == discard_button:
            self.reject()
        return True

    def _go_to_selected_tag(self) -> None:
        item = self.existing_list.currentItem()
        if item is None:
            return
        if not self._confirm_navigation_with_pending_changes():
            return
        window = self.window()
        tag_id = item.data(self.TAG_ID_ROLE)
        assignment_id = item.data(self.ASSIGNMENT_ID_ROLE)
        if hasattr(window, "open_annotation_tag"):
            window.open_annotation_tag(
                tag_id=str(tag_id) if tag_id else None, assignment_id=str(assignment_id) if assignment_id else None
            )
            return
        QMessageBox.information(self, "Open Tag", "Open the Tags page to review this tag assignment.")
