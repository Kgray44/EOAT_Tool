from __future__ import annotations

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import (
        QCheckBox,
        QComboBox,
        QDateEdit,
        QFormLayout,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QPushButton,
        QTextEdit,
        QToolButton,
        QVBoxLayout,
        QWidget,
    )
except ImportError:  # pragma: no cover
    Qt = None
    QCheckBox = QComboBox = QDateEdit = QFormLayout = QHBoxLayout = QLabel = QLineEdit = QPushButton = QTextEdit = (
        QToolButton
    ) = QVBoxLayout = QWidget = None


class NoteEditor(QWidget):
    OPTIONAL_FIELDS = [
        ("Status", "status"),
        ("Collection / Folder", "collection"),
        ("Note Type", "note_type"),
        ("Follow-Up Date", "follow_up_date"),
        ("Linked Audit ID", "linked_audit_id"),
        ("Linked Machine", "linked_machine"),
        ("Linked EOAT / Tool", "linked_eoat_tool"),
        ("Linked Audit Field", "linked_audit_field"),
        ("Linked Fit Check Entry", "linked_compatibility_entry"),
        ("Linked Photo / Attachment", "attachment"),
        ("Linked Workbook Health Warning", "linked_workbook_warning"),
        ("Linked Pilot Candidate", "linked_pilot_candidate"),
        ("Linked Target", "target"),
        ("Related Tags", "tags"),
        ("Created By", "created_by"),
        ("Due / Review Date", "due_review_date"),
        ("Priority Reason", "priority_reason"),
        ("Source / Evidence", "source_evidence"),
        ("Assigned To / Owner", "assigned_to"),
        ("Resolution Notes", "resolution_notes"),
        ("Related Report", "related_report"),
        ("Related PM Checklist Item", "related_pm_checklist_item"),
        ("Related FMEA Item", "related_fmea_item"),
        ("Related Issue", "related_issue"),
        ("Related Standard / Guideline", "related_standard_guideline"),
        ("Related Spare Part / BOM Item", "related_spare_part_bom_item"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.subject_edit = QLineEdit()
        self.body_edit = QTextEdit()
        self.body_edit.setPlaceholderText("Markdown supported: bullets, numbered lists, links, and plain text notes.")
        self.importance_combo = QComboBox()
        self.importance_combo.addItems(["Low", "Neutral", "Important", "Critical"])
        self.importance_combo.setCurrentText("Neutral")
        self.status_combo = QComboBox()
        self.status_combo.addItems(["", "Open", "Resolved", "Archived"])
        self.collection_edit = QLineEdit()
        self.note_type_edit = QLineEdit()
        self.follow_up_edit = QLineEdit()
        self.attachment_edit = QLineEdit()
        self.created_by_edit = QLineEdit()
        self.extra_edits = {
            "linked_audit_id": QLineEdit(),
            "linked_machine": QLineEdit(),
            "linked_eoat_tool": QLineEdit(),
            "linked_audit_field": QLineEdit(),
            "linked_compatibility_entry": QLineEdit(),
            "linked_workbook_warning": QLineEdit(),
            "linked_pilot_candidate": QLineEdit(),
            "due_review_date": QLineEdit(),
            "priority_reason": QLineEdit(),
            "source_evidence": QLineEdit(),
            "assigned_to": QLineEdit(),
            "resolution_notes": QLineEdit(),
            "related_report": QLineEdit(),
            "related_pm_checklist_item": QLineEdit(),
            "related_fmea_item": QLineEdit(),
            "related_issue": QLineEdit(),
            "related_standard_guideline": QLineEdit(),
            "related_spare_part_bom_item": QLineEdit(),
        }
        self.preview = QTextEdit()
        self.preview.setReadOnly(True)

        self.optional_widgets = {
            "status": self.status_combo,
            "collection": self.collection_edit,
            "note_type": self.note_type_edit,
            "follow_up_date": self.follow_up_edit,
            "attachment": self.attachment_edit,
            "created_by": self.created_by_edit,
            **self.extra_edits,
        }

        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.addRow("Subject", self.subject_edit)
        form.addRow("Importance", self.importance_combo)
        form.addRow("Body", self.body_edit)
        self.optional_form = QFormLayout()
        self.optional_labels: dict[str, QLabel] = {}
        for label_text, key in self.OPTIONAL_FIELDS:
            if key in self.optional_widgets:
                label = QLabel(label_text)
                self.optional_labels[key] = label
                self.optional_form.addRow(label, self.optional_widgets[key])
                label.setVisible(False)
                self.optional_widgets[key].setVisible(False)

        action_row = QHBoxLayout()
        self.add_field_button = QToolButton()
        self.add_field_button.setText("+")
        self.add_field_button.setToolTip("Add optional note field")
        action_row.addWidget(self.add_field_button)
        self.preview_checkbox = QCheckBox("Preview")
        self.preview_checkbox.stateChanged.connect(self._toggle_preview)
        action_row.addWidget(self.preview_checkbox)
        action_row.addStretch(1)
        layout.addLayout(action_row)
        layout.addLayout(form)
        layout.addLayout(self.optional_form)
        layout.addWidget(self.preview)
        self.preview.hide()

    def show_optional_field(self, key: str) -> None:
        widget = self.optional_widgets.get(key)
        label = self.optional_labels.get(key)
        if widget is not None:
            widget.setVisible(True)
        if label is not None:
            label.setVisible(True)

    def values(self) -> dict[str, str | None]:
        values = {
            "subject": self.subject_edit.text().strip(),
            "body_markdown": self.body_edit.toPlainText(),
            "importance": self.importance_combo.currentText(),
            "status": self.status_combo.currentText().strip() or None,
            "collection": self.collection_edit.text().strip() or None,
            "note_type": self.note_type_edit.text().strip() or None,
            "follow_up_date": self.follow_up_edit.text().strip() or None,
            "attachment": self.attachment_edit.text().strip() or None,
            "created_by": self.created_by_edit.text().strip() or None,
        }
        for key, widget in self.extra_edits.items():
            values[key] = widget.text().strip() or None
        return values

    def set_values(self, values: dict[str, object]) -> None:
        self.subject_edit.setText(str(values.get("subject") or ""))
        self.body_edit.setPlainText(str(values.get("body_markdown") or ""))
        importance = str(values.get("importance") or "Neutral")
        if self.importance_combo.findText(importance) >= 0:
            self.importance_combo.setCurrentText(importance)
        for key, widget in self.optional_widgets.items():
            value = values.get(key)
            if value:
                self.show_optional_field(key)
            if isinstance(widget, QComboBox):
                widget.setCurrentText(str(value or ""))
            else:
                widget.setText(str(value or ""))
        self._toggle_preview()

    def clear(self) -> None:
        self.subject_edit.clear()
        self.body_edit.clear()
        self.importance_combo.setCurrentText("Neutral")
        for widget in self.optional_widgets.values():
            if isinstance(widget, QComboBox):
                widget.setCurrentText("")
            else:
                widget.clear()

    def _toggle_preview(self) -> None:
        if self.preview_checkbox.isChecked():
            self.preview.setMarkdown(self.body_edit.toPlainText())
            self.preview.show()
        else:
            self.preview.hide()
