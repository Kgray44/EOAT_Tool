from __future__ import annotations

from typing import Any

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import (
        QDialog,
        QDialogButtonBox,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMessageBox,
        QPushButton,
        QTableWidget,
        QTableWidgetItem,
        QVBoxLayout,
        QWidget,
    )
except ImportError:  # pragma: no cover
    Qt = None
    QDialog = QDialogButtonBox = QHBoxLayout = QLabel = QLineEdit = QMessageBox = QPushButton = QTableWidget = (
        QTableWidgetItem
    ) = QVBoxLayout = QWidget = None


def _target_value(target: Any, key: str, default: str = "") -> str:
    if isinstance(target, dict):
        value = target.get(key, default)
    else:
        value = getattr(target, key, default)
    return "" if value is None else str(value)


def _target_dict(target: Any) -> dict[str, object]:
    if isinstance(target, dict):
        return dict(target)
    return {
        "id": _target_value(target, "id"),
        "target_type": _target_value(target, "target_type"),
        "target_label": _target_value(target, "target_label"),
        "audit_id": _target_value(target, "audit_id"),
        "machine_id": _target_value(target, "machine_id"),
        "field_key": _target_value(target, "field_key"),
        "field_label": _target_value(target, "field_label"),
        "object_ref": _target_value(target, "object_ref"),
        "comment": _target_value(target, "comment"),
        "updated_at": _target_value(target, "updated_at") or _target_value(target, "assignment_updated_at"),
    }


class AnnotationTargetPickerDialog(QDialog):
    def __init__(self, targets: list[dict[str, object]], *, title: str = "Select Target for Tag", parent=None):
        super().__init__(parent)
        self.targets = [_target_dict(target) for target in targets]
        self.selected_target: dict[str, object] | None = None
        self.setWindowTitle(title)
        self.resize(860, 420)

        layout = QVBoxLayout(self)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search targets...")
        self.search_edit.textChanged.connect(self._populate)
        layout.addWidget(self.search_edit)

        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(["Type", "Target", "Audit ID", "Machine", "Field", "Comment", "Updated"])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.itemSelectionChanged.connect(self._update_selected)
        self.table.itemDoubleClicked.connect(lambda _item: self._open_selected())
        layout.addWidget(self.table, stretch=1)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self.open_button = QPushButton("Open Selected")
        self.open_button.setEnabled(False)
        self.open_button.clicked.connect(self._open_selected)
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        button_row.addWidget(self.open_button)
        button_row.addWidget(cancel_button)
        layout.addLayout(button_row)
        self._populate()

    def _populate(self) -> None:
        needle = self.search_edit.text().casefold().strip()
        rows = []
        for target in self.targets:
            haystack = " ".join(
                str(target.get(key) or "")
                for key in [
                    "target_type",
                    "target_label",
                    "audit_id",
                    "machine_id",
                    "field_key",
                    "field_label",
                    "comment",
                    "updated_at",
                    "assignment_updated_at",
                ]
            ).casefold()
            if not needle or needle in haystack:
                rows.append(target)
        self.table.setRowCount(len(rows))
        for row_index, target in enumerate(rows):
            values = [
                target.get("target_type"),
                target.get("target_label") or target.get("object_ref"),
                target.get("audit_id"),
                target.get("machine_id"),
                target.get("field_label") or target.get("field_key"),
                target.get("comment"),
                target.get("updated_at") or target.get("assignment_updated_at"),
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value or ""))
                if col == 0:
                    item.setData(Qt.ItemDataRole.UserRole, target)
                if col == 5:
                    item.setToolTip(str(value or ""))
                self.table.setItem(row_index, col, item)
        self.table.resizeColumnsToContents()
        self._update_selected()

    def _update_selected(self) -> None:
        item = self.table.item(self.table.currentRow(), 0)
        self.selected_target = item.data(Qt.ItemDataRole.UserRole) if item else None
        self.open_button.setEnabled(self.selected_target is not None)

    def _open_selected(self) -> None:
        self._update_selected()
        if self.selected_target is None:
            return
        self.accept()


class AnnotationTargetNavigator:
    def __init__(self, owner: QWidget | None):
        self.owner = owner

    def open_targets(self, targets: list[dict[str, object]], *, title: str = "Select Target for Tag") -> bool:
        if not targets:
            self._message("Open Target", "No linked targets are available to open.")
            return False
        if len(targets) == 1:
            return self.open_target(targets[0])
        picker = AnnotationTargetPickerDialog(targets, title=title, parent=self._window_widget())
        if picker.exec() != QDialog.DialogCode.Accepted or picker.selected_target is None:
            return False
        return self.open_target(picker.selected_target)

    def open_target(self, target: Any) -> bool:
        data = _target_dict(target)
        target_type = str(data.get("target_type") or "").strip()
        if target_type in {"audit", "audit_field"}:
            return self._open_audit_target(data)
        if target_type == "machine":
            audit_id = str(data.get("audit_id") or "").strip()
            if audit_id:
                return self._open_audit_target(data)
            machine = str(data.get("machine_id") or data.get("target_label") or "").strip()
            if self._navigate_to_page("press_view"):
                page = self._page("press_view")
                if hasattr(page, "select_machine"):
                    page.select_machine(machine)
                self._page_message(
                    "press_view", f"Machine target opened: {data.get('target_label') or machine or 'machine'}."
                )
                return True
            return self._open_page_with_message(
                "audit_progress",
                f"Machine target opened as far as possible: {data.get('target_label') or machine or 'machine'}.",
            )
        if target_type == "note":
            note_id = str(data.get("object_ref") or data.get("id") or "").strip()
            self._navigate_to_page("notes")
            page = self._page("notes")
            if note_id and hasattr(page, "select_note"):
                page.select_note(note_id)
            return True
        if target_type == "tag_assignment":
            assignment_id = str(data.get("object_ref") or data.get("id") or "").strip()
            return self.open_tag(assignment_id=assignment_id)
        if target_type == "compatibility_entry":
            self._navigate_to_page("audit")
            self._page_message(
                "audit",
                f"Opened EOAT Audit. Fit Check target: {data.get('target_label') or data.get('object_ref') or 'entry'}.",
            )
            return True
        if target_type == "photo":
            return self._open_page_with_message(
                "photos", f"Photo/documentation target: {data.get('target_label') or data.get('object_ref') or 'item'}."
            )
        if target_type == "workbook_warning":
            return self._open_page_with_message(
                "workbook_health",
                f"Workbook warning target: {data.get('target_label') or data.get('object_ref') or 'warning'}.",
            )
        if target_type == "pilot_candidate":
            return self._open_page_with_message(
                "pilot_candidates",
                f"Pilot candidate target: {data.get('target_label') or data.get('object_ref') or 'candidate'}.",
            )
        self._message("Open Target", "This target type cannot be opened directly yet.")
        return False

    def open_tag(self, *, tag_id: str | None = None, assignment_id: str | None = None) -> bool:
        self._navigate_to_page("tags")
        page = self._page("tags")
        if hasattr(page, "select_tag_or_assignment"):
            page.select_tag_or_assignment(tag_id=tag_id, assignment_id=assignment_id)
        return True

    def _open_audit_target(self, target: dict[str, object]) -> bool:
        audit_id = str(target.get("audit_id") or "").strip()
        field = str(target.get("field_label") or target.get("field_key") or "").strip()
        self._navigate_to_page("audit")
        page = self._page("audit")
        if page is None:
            self._message("Open Target", "EOAT Audit page is not available.")
            return False
        if audit_id and hasattr(page, "load_existing_audit"):
            message = f"Opened {audit_id}. Target field: {field}." if field else f"Opened {audit_id}."
            page.load_existing_audit(audit_id, loaded_message=message)
        if hasattr(page, "focus_annotation_target"):
            page.focus_annotation_target(target)
        elif field:
            self._page_message("audit", f"Opened {audit_id or 'audit'}. Target field: {field}.")
        return True

    def _open_page_with_message(self, page_key: str, message: str) -> bool:
        if not self._navigate_to_page(page_key):
            self._message("Open Target", message)
            return False
        self._page_message(page_key, message)
        return True

    def _navigate_to_page(self, page_key: str) -> bool:
        window = self._window()
        if hasattr(window, "_navigate_to_page"):
            window._navigate_to_page(page_key)
            return True
        if hasattr(window, "_show_page"):
            window._show_page(page_key)
            return True
        return False

    def _page(self, page_key: str):
        window = self._window()
        return getattr(window, "pages", {}).get(page_key)

    def _page_message(self, page_key: str, message: str) -> None:
        page = self._page(page_key)
        result_panel = getattr(page, "result_panel", None)
        if result_panel is not None and hasattr(result_panel, "show_text"):
            result_panel.show_text(message)
            return
        status_label = getattr(page, "status_label", None)
        if status_label is not None and hasattr(status_label, "setText"):
            status_label.setText(message)
            return
        self._status(message)

    def _status(self, message: str) -> None:
        window = self._window()
        if hasattr(window, "statusBar"):
            window.statusBar().showMessage(message, 9000)

    def _message(self, title: str, message: str) -> None:
        parent = self._window_widget()
        if QMessageBox is not None:
            QMessageBox.information(parent, title, message)
        self._status(message)

    def _window(self):
        if self.owner is None:
            return None
        return self.owner.window() if hasattr(self.owner, "window") else self.owner

    def _window_widget(self):
        window = self._window()
        return window if isinstance(window, QWidget) else None
