from __future__ import annotations

try:
    from PySide6.QtWidgets import QComboBox, QFormLayout, QLineEdit, QWidget
except ImportError:  # pragma: no cover
    QComboBox = QFormLayout = QLineEdit = QWidget = None


class AnnotationTargetPicker(QWidget):
    TARGET_TYPES = [
        ("Audit", "audit"),
        ("Audit Field", "audit_field"),
        ("Machine", "machine"),
        ("Note", "note"),
        ("Compatibility Entry", "compatibility_entry"),
        ("Photo / Documentation Item", "photo"),
        ("Workbook Health Warning", "workbook_warning"),
        ("Pilot Candidate", "pilot_candidate"),
        ("General Project Item", "project_item"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.target_type_combo = QComboBox()
        for label, value in self.TARGET_TYPES:
            self.target_type_combo.addItem(label, value)
        self.audit_id_edit = QLineEdit()
        self.machine_edit = QLineEdit()
        self.field_edit = QLineEdit()
        self.label_edit = QLineEdit()
        self.object_ref_edit = QLineEdit()
        layout = QFormLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addRow("Target Type", self.target_type_combo)
        layout.addRow("Audit ID", self.audit_id_edit)
        layout.addRow("Machine", self.machine_edit)
        layout.addRow("Audit Field", self.field_edit)
        layout.addRow("Label", self.label_edit)
        layout.addRow("Object Ref / Path", self.object_ref_edit)

    def target_kwargs(self) -> dict[str, str]:
        field = self.field_edit.text().strip()
        return {
            "target_type": str(self.target_type_combo.currentData() or "project_item"),
            "target_label": self.label_edit.text().strip(),
            "audit_id": self.audit_id_edit.text().strip(),
            "machine_id": self.machine_edit.text().strip(),
            "field_key": field,
            "field_label": field,
            "sheet_name": "EOAT Inventory" if field else "",
            "header_name": field,
            "object_ref": self.object_ref_edit.text().strip(),
        }
