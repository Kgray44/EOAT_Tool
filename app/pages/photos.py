from __future__ import annotations

from datetime import date
from pathlib import Path

try:
    from PySide6.QtCore import Qt
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
    Qt = None
    QApplication = QCheckBox = QComboBox = QFormLayout = QHBoxLayout = QLabel = QLineEdit = QListWidget = (
        QListWidgetItem
    ) = QPushButton = QTableWidget = QTableWidgetItem = QTextEdit = QVBoxLayout = QWidget = None

if QComboBox is not None:

    class LookupComboBox(QComboBox):
        """Editable combo that keeps the QLineEdit-style API used by this page."""

        def __init__(self, parent=None):
            super().__init__(parent)
            self.setEditable(True)
            self.setMinimumContentsLength(18)
            self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
            completer = self.completer()
            if Qt is not None and completer is not None:
                completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

        @property
        def editingFinished(self):
            return self.lineEdit().editingFinished

        def text(self) -> str:
            raw = self.currentText().strip()
            index = self.currentIndex()
            if index >= 0 and raw == self.itemText(index).strip():
                value = self.currentData()
                if value is not None and str(value).strip():
                    return str(value).strip()
            if " | " in raw:
                return raw.split(" | ", 1)[0].strip()
            return raw

        def setText(self, value: object) -> None:
            self.set_lookup_text(value)

        def set_lookup_text(self, value: object, *, block_signals: bool = False) -> None:
            previous_blocked = self.blockSignals(True) if block_signals else None
            try:
                text = str(value or "").strip()
                index = self.findData(text)
                if index < 0:
                    index = self.findText(text)
                if index >= 0:
                    self.setCurrentIndex(index)
                else:
                    self.setCurrentIndex(-1)
                    self.setEditText(text)
            finally:
                if previous_blocked is not None:
                    self.blockSignals(previous_blocked)

else:  # pragma: no cover
    LookupComboBox = None

from app.page_tasks import run_tool_background
from app.widgets.tool_run_panel import ToolRunPanel
from core.audit_field_links import friendly_audit_field_label, parse_audit_field_link
from core.openers import open_path
from core.paths import resolve_project_paths
from core.photo_evidence import (
    audit_photo_intake_folder,
    create_audit_photo_intake_folder,
    evidence_coverage_for_audit,
    export_photo_checklist,
    indexed_photos_for_audit,
    link_photo_to_audit_field,
    linked_audit_field_for_photo,
    resolve_indexed_photo_path,
)
from core.photo_indexing import PHOTO_VIEW_FOLDERS, intake_photos, list_incoming_photos, preview_photo_intake
from core.tool_fields import TOOL_FIELD
from core.workbook_cache import row_dicts_cached


class PhotosPage(QWidget):
    BATCH_INCLUDE_COL = 0
    BATCH_SOURCE_COL = 1
    BATCH_TARGET_COL = 2
    BATCH_VIEW_COL = 3
    BATCH_DESCRIPTION_COL = 4
    BATCH_AUDIT_COL = 5
    BATCH_ISSUE_COL = 6
    BATCH_FIELD_COL = 7

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.audit_lookup_rows: list[dict[str, object]] = []
        self.issue_lookup_rows: list[dict[str, object]] = []
        self._last_autofilled_tool_number = ""
        self.next_shot_type = "Overall EOAT"
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
        self.tool_edit = QLineEdit()
        self.date_edit = QLineEdit(date.today().isoformat())
        self.view_combo = QComboBox()
        self.view_combo.addItems(list(PHOTO_VIEW_FOLDERS.keys()))
        self.audit_lookup_combo = QComboBox()
        self.audit_lookup_combo.setEditable(True)
        self.audit_context_label = QLabel("")
        self.audit_context_label.setWordWrap(True)
        self.audit_context_label.setStyleSheet("color: #475569;")
        self.audit_id_edit = LookupComboBox()
        self.issue_id_edit = LookupComboBox()
        self.audit_field_link_edit = QLineEdit()
        self.audit_field_link_edit.setPlaceholderText("audit_id=...;field_key=...;field_label=...")
        self.audit_field_link_edit.textChanged.connect(lambda _text: self._update_go_to_link_button())
        self.go_to_link_button = QPushButton("Go to Link")
        self.go_to_link_button.setToolTip("Return to the audit field linked to this photo.")
        self.go_to_link_button.clicked.connect(self.go_to_audit_field_link)
        self.link_display_label = QLabel("")
        self.link_display_label.setWordWrap(True)
        self.link_display_label.setStyleSheet("color: #475569;")
        self.description_edit = QTextEdit()
        self.description_edit.setFixedHeight(70)
        self.notes_edit = QTextEdit()
        self.notes_edit.setFixedHeight(60)
        self.copy_check = QCheckBox("Copy photos instead of moving originals")
        self.copy_check.setChecked(True)
        for label, widget in [
            ("Plant/Area", self.plant_edit),
            ("Press/Machine #", self.press_edit),
            ("Tool #", self.tool_edit),
            ("Date Taken", self.date_edit),
            ("EOAT Area Shown", self.view_combo),
            ("Audit Lookup", self.audit_lookup_combo),
            ("Related Audit ID", self.audit_id_edit),
            ("Audit Context", self.audit_context_label),
            ("Related Issue ID", self.issue_id_edit),
        ]:
            form.addRow(label, widget)
        link_row = QHBoxLayout()
        link_row.addWidget(self.audit_field_link_edit, stretch=1)
        link_row.addWidget(self.go_to_link_button)
        form.addRow("Link to Audit Field", link_row)
        form.addRow("Linked Target", self.link_display_label)
        for label, widget in [
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

        batch_heading = QLabel("Batch Review")
        batch_heading.setStyleSheet("font-weight: 600;")
        layout.addWidget(batch_heading)
        batch_actions = QHBoxLayout()
        for label, callback in [
            ("Build Batch Review", self.build_batch_review),
            ("Refresh Batch Preview", self.refresh_batch_preview),
        ]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            batch_actions.addWidget(button)
        layout.addLayout(batch_actions)
        self.batch_table = QTableWidget(0, 8)
        self.batch_table.setHorizontalHeaderLabels(
            [
                "Include?",
                "Source filename",
                "Preview target filename",
                "EOAT Area Shown",
                "Description",
                "Related Audit ID",
                "Related Issue ID",
                "Linked Audit Field",
            ]
        )
        layout.addWidget(self.batch_table, stretch=1)

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
            ("Use Next Missing Shot Type", self.use_next_missing_shot_type),
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
        self.evidence_table.setHorizontalHeaderLabels(
            ["Category", "Applies", "Required", "Present", "Photos", "Status", "Warning"]
        )
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
        self.indexed_photos_table.itemSelectionChanged.connect(self._update_go_to_link_button)
        layout.addWidget(self.indexed_photos_table, stretch=1)

        self.result_panel = ToolRunPanel()
        layout.addWidget(self.result_panel, stretch=1)
        self.audit_lookup_combo.currentIndexChanged.connect(self.apply_selected_audit)
        self.audit_id_edit.activated.connect(lambda _index: self.refresh_audit_context())
        self.audit_id_edit.editingFinished.connect(self.refresh_audit_context)
        self.view_combo.currentTextChanged.connect(lambda _text: self.refresh_batch_preview(show_result=False))
        self.refresh_audit_lookup()
        self.refresh_incoming()
        self._update_go_to_link_button()

    def refresh(self) -> None:
        self.refresh_audit_lookup()
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

    def refresh_audit_lookup(self) -> None:
        self.audit_lookup_rows = self._load_audit_rows()
        self.issue_lookup_rows = self._load_issue_rows()
        self.audit_lookup_combo.blockSignals(True)
        self.audit_lookup_combo.clear()
        self.audit_lookup_combo.addItem("Select audit row", None)
        for row in self.audit_lookup_rows:
            self.audit_lookup_combo.addItem(self._audit_lookup_label(row), row)
        self.audit_lookup_combo.blockSignals(False)
        self._populate_related_audit_options()
        self._populate_related_issue_options()

    def _load_audit_rows(self) -> list[dict[str, object]]:
        paths = resolve_project_paths(self.config.project_root)
        if not paths.master_workbook.exists():
            return []
        try:
            return [
                dict(row)
                for row in row_dicts_cached(paths.master_workbook, "EOAT Inventory")
                if str(row.get("Audit ID") or "").strip()
            ]
        except Exception:
            return []

    def _load_issue_rows(self) -> list[dict[str, object]]:
        paths = resolve_project_paths(self.config.project_root)
        if not paths.master_workbook.exists():
            return []
        try:
            return [
                dict(row)
                for row in row_dicts_cached(paths.master_workbook, "Issue Log")
                if str(row.get("Issue ID") or "").strip()
            ]
        except Exception:
            return []

    def _audit_lookup_label(self, row: dict[str, object]) -> str:
        parts = [
            str(row.get("Audit ID") or "").strip(),
            str(row.get("Press/Machine #") or "").strip(),
            str(row.get(TOOL_FIELD) or "").strip(),
            str(row.get("Part Family") or "").strip(),
            str(row.get("Part Name/Description") or "").strip(),
        ]
        return " | ".join(part for part in parts if part)

    def _issue_lookup_label(self, row: dict[str, object]) -> str:
        parts = [
            str(row.get("Issue ID") or "").strip(),
            str(row.get("Press/Machine #") or "").strip(),
            str(row.get("Issue Category") or "").strip(),
            str(row.get("Status") or "").strip(),
        ]
        return " | ".join(part for part in parts if part)

    def _populate_related_audit_options(self) -> None:
        current = self.audit_id_edit.text()
        options = [
            (self._audit_lookup_label(row), str(row.get("Audit ID") or "").strip())
            for row in self.audit_lookup_rows
            if str(row.get("Audit ID") or "").strip()
        ]
        self._populate_lookup_options(self.audit_id_edit, options, current)

    def _populate_related_issue_options(self) -> None:
        current = self.issue_id_edit.text()
        options = [
            (self._issue_lookup_label(row), str(row.get("Issue ID") or "").strip())
            for row in self.issue_lookup_rows
            if str(row.get("Issue ID") or "").strip()
        ]
        self._populate_lookup_options(self.issue_id_edit, options, current)

    def _populate_lookup_options(
        self, combo: LookupComboBox, options: list[tuple[str, str]], current: str = ""
    ) -> None:
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("", "")
        for label, value in options:
            if not value:
                continue
            combo.addItem(label or value, value)
            if Qt is not None:
                combo.setItemData(combo.count() - 1, label or value, Qt.ItemDataRole.ToolTipRole)
        combo.set_lookup_text(current, block_signals=True)
        combo.blockSignals(False)

    def _make_lookup_combo(self, options: list[tuple[str, str]], current: str = "") -> LookupComboBox:
        combo = LookupComboBox()
        self._populate_lookup_options(combo, options, current)
        return combo

    def _make_audit_id_combo(self, current: str = "") -> LookupComboBox:
        options = [
            (self._audit_lookup_label(row), str(row.get("Audit ID") or "").strip())
            for row in self.audit_lookup_rows
            if str(row.get("Audit ID") or "").strip()
        ]
        return self._make_lookup_combo(options, current)

    def _make_issue_id_combo(self, current: str = "") -> LookupComboBox:
        options = [
            (self._issue_lookup_label(row), str(row.get("Issue ID") or "").strip())
            for row in self.issue_lookup_rows
            if str(row.get("Issue ID") or "").strip()
        ]
        return self._make_lookup_combo(options, current)

    def apply_selected_audit(self) -> None:
        row = self.audit_lookup_combo.currentData()
        if isinstance(row, dict):
            self._apply_audit_row(row)

    def refresh_audit_context(self) -> None:
        audit_id = self.audit_id_edit.text().strip()
        if not audit_id:
            self.audit_context_label.setText("")
            return
        row = self._find_audit_row(audit_id)
        if row is None:
            self.audit_context_label.setText("No matching audit row found.")
            return
        self._apply_audit_row(row, preserve_description=True)

    def _find_audit_row(self, query: str) -> dict[str, object] | None:
        folded = query.strip().casefold()
        if not folded:
            return None
        for row in self.audit_lookup_rows or self._load_audit_rows():
            candidates = [
                row.get("Audit ID"),
                row.get("Press/Machine #"),
                row.get(TOOL_FIELD),
                row.get("Part Family"),
                row.get("Part Name/Description"),
            ]
            if any(str(candidate or "").strip().casefold() == folded for candidate in candidates):
                return row
        for row in self.audit_lookup_rows or self._load_audit_rows():
            haystack = self._audit_lookup_label(row).casefold()
            if folded in haystack:
                return row
        return None

    def _apply_audit_row(self, row: dict[str, object], *, preserve_description: bool = False) -> None:
        audit_id = str(row.get("Audit ID") or "").strip()
        plant = str(row.get("Plant/Area") or "").strip()
        press = str(row.get("Press/Machine #") or "").strip()
        if audit_id:
            self.audit_id_edit.set_lookup_text(audit_id, block_signals=True)
        if plant:
            self.plant_edit.setText(plant)
        if press:
            self.press_edit.setText(press)
        self._apply_audit_tool_number(str(row.get(TOOL_FIELD) or "").strip())
        if not preserve_description or not self.description_edit.toPlainText().strip():
            self.description_edit.setPlainText(self._default_description(row))
        self.audit_context_label.setText(
            " | ".join(
                part
                for part in [
                    f"EOAT Type: {row.get('EOAT Type') or 'N/A'}",
                    f"Tool #: {row.get(TOOL_FIELD) or 'N/A'}",
                    f"Part Family: {row.get('Part Family') or 'N/A'}",
                    f"Part: {row.get('Part Name/Description') or 'N/A'}",
                    f"Status: {row.get('Status') or 'N/A'}",
                    f"Photos Taken?: {row.get('Photos Taken?') or 'N/A'}",
                ]
                if part
            )
        )
        self.refresh_batch_defaults()
        self.refresh_evidence_coverage()

    def _apply_audit_tool_number(self, tool_number: str) -> None:
        if not tool_number:
            return
        current = self.tool_edit.text().strip()
        if not current or current == self._last_autofilled_tool_number:
            self.tool_edit.setText(tool_number)
            self._last_autofilled_tool_number = tool_number

    def _default_description(self, row: dict[str, object]) -> str:
        audit_id = str(row.get("Audit ID") or "").strip()
        machine = str(row.get("Press/Machine #") or "").strip()
        tool = self.tool_edit.text().strip() or str(row.get(TOOL_FIELD) or "").strip()
        pieces = [f"Photo evidence for {audit_id}" if audit_id else "Photo evidence"]
        if machine:
            pieces.append(f"Machine {machine}")
        if tool:
            pieces.append(f"Tool {tool}")
        return ", ".join(pieces)

    def metadata(self) -> dict[str, str]:
        return {
            "plant_area": self.plant_edit.text().strip(),
            "press_machine": self.press_edit.text().strip(),
            "tool_number": self.tool_edit.text().strip(),
            "date_taken": self.date_edit.text().strip(),
            "view_type": self.view_combo.currentText(),
            "related_audit_id": self.audit_id_edit.text().strip(),
            "related_issue_id": self.issue_id_edit.text().strip(),
            "audit_field_link": self.audit_field_link_edit.text().strip(),
            "description": self.description_edit.toPlainText().strip(),
            "notes": self.notes_edit.toPlainText().strip(),
        }

    def apply_pending_audit_field_link(self, link_text: str) -> None:
        self.audit_field_link_edit.setText(str(link_text or "").strip())
        label = friendly_audit_field_label(link_text)
        if label:
            self.link_display_label.setText(label)
            parsed = parse_audit_field_link(link_text)
            if parsed is not None:
                self.audit_id_edit.setText(parsed.audit_id)
                if parsed.machine_number and not self.press_edit.text().strip():
                    self.press_edit.setText(parsed.machine_number)
                if parsed.tool_number and not self.tool_edit.text().strip():
                    self.tool_edit.setText(parsed.tool_number)
                self.refresh_audit_context()
            self.result_panel.show_text(f"Ready to attach photo to: {label}")
        else:
            self.link_display_label.setText("")
        self._update_go_to_link_button()

    def build_batch_review(self) -> None:
        photos = self.selected_photos()
        self.batch_table.setRowCount(0)
        for photo in photos:
            row_index = self.batch_table.rowCount()
            self.batch_table.insertRow(row_index)

            include = QCheckBox()
            include.setChecked(True)
            self.batch_table.setCellWidget(row_index, self.BATCH_INCLUDE_COL, include)

            source_item = QTableWidgetItem(Path(photo).name)
            source_item.setToolTip(photo)
            if Qt is not None:
                source_item.setData(Qt.ItemDataRole.UserRole, photo)
            self.batch_table.setItem(row_index, self.BATCH_SOURCE_COL, source_item)
            self.batch_table.setItem(row_index, self.BATCH_TARGET_COL, QTableWidgetItem(""))

            view = QComboBox()
            view.addItems(list(PHOTO_VIEW_FOLDERS.keys()))
            view.setCurrentText(self.view_combo.currentText())
            view.currentTextChanged.connect(lambda _text: self.refresh_batch_preview(show_result=False))
            self.batch_table.setCellWidget(row_index, self.BATCH_VIEW_COL, view)

            self.batch_table.setItem(
                row_index, self.BATCH_DESCRIPTION_COL, QTableWidgetItem(self.description_edit.toPlainText().strip())
            )
            self.batch_table.setCellWidget(
                row_index, self.BATCH_AUDIT_COL, self._make_audit_id_combo(self.audit_id_edit.text().strip())
            )
            self.batch_table.setCellWidget(
                row_index, self.BATCH_ISSUE_COL, self._make_issue_id_combo(self.issue_id_edit.text().strip())
            )
            self.batch_table.setItem(
                row_index, self.BATCH_FIELD_COL, QTableWidgetItem(self.audit_field_link_edit.text().strip())
            )
        self.refresh_batch_preview(show_result=False)

    def refresh_batch_defaults(self) -> None:
        if self.batch_table.rowCount() == 0:
            return
        for row_index in range(self.batch_table.rowCount()):
            self._set_batch_lookup_text(row_index, self.BATCH_AUDIT_COL, self.audit_id_edit.text().strip())
            self._set_batch_lookup_text(row_index, self.BATCH_ISSUE_COL, self.issue_id_edit.text().strip())
            description_item = self.batch_table.item(row_index, self.BATCH_DESCRIPTION_COL)
            if description_item is not None and not description_item.text().strip():
                description_item.setText(self.description_edit.toPlainText().strip())
        self.refresh_batch_preview(show_result=False)

    def _set_batch_lookup_text(self, row_index: int, column: int, value: str) -> None:
        widget = self.batch_table.cellWidget(row_index, column)
        if isinstance(widget, LookupComboBox) and not widget.text().strip():
            widget.set_lookup_text(value, block_signals=True)
            return
        item = self.batch_table.item(row_index, column)
        if item is not None and not item.text().strip():
            item.setText(value)

    def refresh_batch_preview(self, show_result: bool = True) -> None:
        if self.batch_table.rowCount() == 0:
            return
        photos, metadata = self.selected_batch_metadata()
        if not photos:
            if show_result:
                self.result_panel.show_text("No batch rows are included.")
            return
        data = self.metadata()
        plan = preview_photo_intake(
            self.config.project_root,
            photos,
            data["plant_area"],
            data["press_machine"],
            data["date_taken"],
            data["view_type"],
            tool_number=data["tool_number"],
            per_photo_metadata=metadata,
        )
        included_rows = self._included_batch_rows()
        for row_index, item in zip(included_rows, plan):
            self.batch_table.setItem(row_index, self.BATCH_TARGET_COL, QTableWidgetItem(item.target.name))
        if show_result:
            self.result_panel.show_text("\n".join(f"{item.source} -> {item.target}" for item in plan))

    def selected_batch_metadata(self) -> tuple[list[str], list[dict[str, str]]]:
        photos: list[str] = []
        metadata: list[dict[str, str]] = []
        for row_index in self._included_batch_rows():
            source = self._batch_source(row_index)
            if not source:
                continue
            photos.append(source)
            metadata.append(
                {
                    "source": source,
                    "view_type": self._batch_view_type(row_index),
                    "description": self._batch_item_text(row_index, self.BATCH_DESCRIPTION_COL),
                    "related_audit_id": self._batch_item_text(row_index, self.BATCH_AUDIT_COL),
                    "related_issue_id": self._batch_item_text(row_index, self.BATCH_ISSUE_COL),
                    "linked_audit_field": self._batch_item_text(row_index, self.BATCH_FIELD_COL),
                }
            )
        return photos, metadata

    def _included_batch_rows(self) -> list[int]:
        rows: list[int] = []
        for row_index in range(self.batch_table.rowCount()):
            include = self.batch_table.cellWidget(row_index, self.BATCH_INCLUDE_COL)
            if isinstance(include, QCheckBox) and not include.isChecked():
                continue
            rows.append(row_index)
        return rows

    def _batch_source(self, row_index: int) -> str:
        item = self.batch_table.item(row_index, self.BATCH_SOURCE_COL)
        if item is None:
            return ""
        if Qt is not None:
            value = item.data(Qt.ItemDataRole.UserRole)
            if value:
                return str(value)
        return item.toolTip() or item.text()

    def _batch_view_type(self, row_index: int) -> str:
        widget = self.batch_table.cellWidget(row_index, self.BATCH_VIEW_COL)
        if isinstance(widget, QComboBox):
            return widget.currentText()
        return self.view_combo.currentText()

    def _batch_item_text(self, row_index: int, column: int) -> str:
        widget = self.batch_table.cellWidget(row_index, column)
        if isinstance(widget, LookupComboBox):
            return widget.text().strip()
        if isinstance(widget, QComboBox):
            return widget.currentText().strip()
        item = self.batch_table.item(row_index, column)
        return item.text().strip() if item is not None else ""

    def _current_audit_field_link_text(self) -> str:
        text = self.audit_field_link_edit.text().strip()
        if text:
            return text
        row_index = self.indexed_photos_table.currentRow()
        if row_index < 0:
            return ""
        item = self.indexed_photos_table.item(row_index, 4)
        return item.text().strip() if item is not None else ""

    def _update_go_to_link_button(self) -> None:
        if not hasattr(self, "go_to_link_button"):
            return
        text = self._current_audit_field_link_text()
        label = friendly_audit_field_label(text)
        self.go_to_link_button.setEnabled(bool(label))
        if label:
            self.link_display_label.setText(label)
        elif text:
            self.link_display_label.setText("Go to Link unavailable for this older/manual link.")
        else:
            self.link_display_label.setText("")

    def go_to_audit_field_link(self) -> None:
        link_text = self._current_audit_field_link_text()
        if not link_text:
            self.result_panel.show_text("Enter or select a linked audit field first.")
            return
        if parse_audit_field_link(link_text) is None:
            self.result_panel.show_text("Go to Link unavailable for this older/manual link.")
            return
        window = self.window()
        if hasattr(window, "navigate_to_audit_field_link") and window.navigate_to_audit_field_link(link_text):
            return
        self.result_panel.show_text("Could not open the linked audit field from this window.")

    def preview_plan(self) -> None:
        data = self.metadata()
        if self.batch_table.rowCount() > 0:
            self.refresh_batch_preview()
            return
        plan = preview_photo_intake(
            self.config.project_root,
            self.selected_photos(),
            data["plant_area"],
            data["press_machine"],
            data["date_taken"],
            data["view_type"],
            tool_number=data["tool_number"],
        )
        if not plan:
            self.result_panel.show_text("No selected supported photos to preview.")
            return
        self.result_panel.show_text("\n".join(f"{item.source} -> {item.target}" for item in plan))

    def confirm_intake(self) -> None:
        data = self.metadata()
        if self.batch_table.rowCount() > 0:
            photos, per_photo_metadata = self.selected_batch_metadata()
        else:
            photos = self.selected_photos()
            per_photo_metadata = None
        run_tool_background(
            self.result_panel,
            "photo_intake_confirm",
            "Photo Intake",
            lambda: intake_photos(
                self.config.project_root,
                photos,
                data["plant_area"],
                data["press_machine"],
                data["date_taken"],
                data["view_type"],
                tool_number=data["tool_number"],
                related_audit_id=data["related_audit_id"],
                related_issue_id=data["related_issue_id"],
                description=data["description"],
                notes=data["notes"],
                linked_audit_field=data["audit_field_link"],
                per_photo_metadata=per_photo_metadata,
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
            self.refresh_indexed_photos(show_empty=False)

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
        self.next_shot_type = "Overall EOAT"
        self.refresh_indexed_photos(show_empty=False)
        if not audit_id:
            self.result_panel.show_text("Enter a Related Audit ID to review photo evidence coverage.")
            return
        coverage = evidence_coverage_for_audit(self.config.project_root, audit_id)
        if coverage is None:
            self.result_panel.show_text(
                f"No audit row found for {audit_id}. You can still create an intake folder for phone photos."
            )
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
        recommended = [
            status.label
            for status in coverage.statuses
            if status.applies and not status.required and not status.present
        ]
        if missing:
            self.next_shot_type = missing[0]
        elif recommended:
            self.next_shot_type = recommended[0]
        else:
            self.next_shot_type = "Overall EOAT"
        if missing:
            self.missing_shots_label.setText(
                "Missing shot types: " + ", ".join(missing) + f". Next: {self.next_shot_type}"
            )
        elif recommended:
            self.missing_shots_label.setText(
                "Recommended shot types: " + ", ".join(recommended) + f". Next: {self.next_shot_type}"
            )
        else:
            self.missing_shots_label.setText("Missing shot types: none")
        self.result_panel.show_text(
            f"Evidence coverage for {coverage.audit_id}: "
            f"{coverage.complete_count} complete, {coverage.missing_required_count} required missing."
        )

    def use_next_missing_shot_type(self) -> None:
        shot_type = self.next_shot_type or "Overall EOAT"
        self.view_combo.setCurrentText(shot_type)
        for row_index in range(self.batch_table.rowCount()):
            widget = self.batch_table.cellWidget(row_index, self.BATCH_VIEW_COL)
            if isinstance(widget, QComboBox):
                widget.setCurrentText(shot_type)
        self.refresh_batch_preview(show_result=False)
        self.result_panel.show_text(f"EOAT Area Shown set to {shot_type}.")

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
            linked_field = linked_audit_field_for_photo(row)
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
