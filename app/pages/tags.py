from __future__ import annotations

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import (
        QComboBox,
        QFormLayout,
        QHeaderView,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMessageBox,
        QPushButton,
        QSplitter,
        QTableWidget,
        QTableWidgetItem,
        QTextEdit,
        QVBoxLayout,
        QWidget,
    )
except ImportError:  # pragma: no cover
    Qt = None
    QComboBox = QFormLayout = QHeaderView = QHBoxLayout = QLabel = QLineEdit = QMessageBox = QPushButton = QSplitter = QTableWidget = QTableWidgetItem = QTextEdit = QVBoxLayout = QWidget = None

from app.widgets.annotation_target_navigator import AnnotationTargetNavigator
from core.annotations.service import AnnotationService
from core.annotations.tag_colors import TAG_COLOR_PALETTE


class TagsPage(QWidget):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.service = AnnotationService(config.project_root)
        self.selected_tag_id: str | None = None

        layout = QVBoxLayout(self)
        heading = QLabel("Tags")
        heading.setStyleSheet("font-size: 18pt; font-weight: 600;")
        layout.addWidget(heading)

        filter_row = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search tags, targets, audit IDs, machine numbers, and comments...")
        self.search_edit.textChanged.connect(self.refresh)
        self.color_filter = QComboBox()
        self.color_filter.addItem("All", "All")
        for color in TAG_COLOR_PALETTE.values():
            self.color_filter.addItem(color.label, color.key)
        self.color_filter.currentTextChanged.connect(self.refresh)
        self.target_filter = QComboBox()
        self.target_filter.addItems(["All", "audit", "audit_field", "machine", "note", "compatibility_entry", "photo", "workbook_warning", "pilot_candidate", "project_item"])
        self.target_filter.currentTextChanged.connect(self.refresh)
        self.sort_combo = QComboBox()
        self.sort_combo.addItems(["Updated Date", "Tag Name", "Color", "Target Type"])
        self.sort_combo.currentTextChanged.connect(self.refresh)
        export_md = QPushButton("Export Markdown")
        export_md.clicked.connect(self.export_markdown)
        export_xlsx = QPushButton("Export Excel")
        export_xlsx.clicked.connect(self.export_excel)
        for widget in [self.search_edit, self.color_filter, self.target_filter, self.sort_combo, export_md, export_xlsx]:
            filter_row.addWidget(widget)
        layout.addLayout(filter_row)

        splitter = QSplitter()
        left = QWidget()
        left_layout = QVBoxLayout(left)
        self.tag_table = QTableWidget()
        self.tag_table.setColumnCount(4)
        self.tag_table.setHorizontalHeaderLabels(["Tag", "Color", "Default", "Updated"])
        self.tag_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.tag_table.itemSelectionChanged.connect(self.load_selected_tag)
        left_layout.addWidget(QLabel("Tag Manager"))
        left_layout.addWidget(self.tag_table)

        form = QFormLayout()
        self.name_edit = QLineEdit()
        self.color_combo = QComboBox()
        for color in TAG_COLOR_PALETTE.values():
            self.color_combo.addItem(color.label, color.key)
        self.description_edit = QTextEdit()
        self.description_edit.setFixedHeight(80)
        form.addRow("Name", self.name_edit)
        form.addRow("Color", self.color_combo)
        form.addRow("Description", self.description_edit)
        left_layout.addLayout(form)
        action_row = QHBoxLayout()
        new_button = QPushButton("+ New Tag")
        new_button.clicked.connect(self.new_tag)
        save_button = QPushButton("Save Tag")
        save_button.clicked.connect(self.save_tag)
        archive_button = QPushButton("Archive Tag")
        archive_button.clicked.connect(self.archive_tag)
        action_row.addWidget(new_button)
        action_row.addWidget(save_button)
        action_row.addWidget(archive_button)
        left_layout.addLayout(action_row)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.addWidget(QLabel("Tagged Targets"))
        self.assignment_table = QTableWidget()
        self.assignment_table.setColumnCount(8)
        self.assignment_table.setHorizontalHeaderLabels(["Tag", "Color", "Target Type", "Target", "Audit ID", "Machine", "Field", "Comment"])
        self.assignment_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.assignment_table.setAlternatingRowColors(True)
        self.assignment_table.setWordWrap(True)
        self.assignment_table.itemSelectionChanged.connect(self._update_go_to_target_state)
        self.assignment_table.itemDoubleClicked.connect(lambda _item: self.go_to_target())
        self.assignment_table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        right_layout.addWidget(self.assignment_table)
        bulk_row = QHBoxLayout()
        self.go_to_target_button = QPushButton("Go to Target")
        self.go_to_target_button.clicked.connect(self.go_to_target)
        remove_selected = QPushButton("Archive Selected Assignments")
        remove_selected.clicked.connect(self.archive_selected_assignments)
        sync_button = QPushButton("Sync Workbook Colors")
        sync_button.clicked.connect(self.sync_colors)
        bulk_row.addWidget(self.go_to_target_button)
        bulk_row.addWidget(remove_selected)
        bulk_row.addWidget(sync_button)
        bulk_row.addStretch(1)
        right_layout.addLayout(bulk_row)
        splitter.addWidget(right)
        splitter.setSizes([390, 690])
        layout.addWidget(splitter, stretch=1)

        self.status_label = QLabel()
        self.status_label.setObjectName("MutedText")
        layout.addWidget(self.status_label)
        self.refresh()

    def refresh(self) -> None:
        self.refresh_tags()
        self.refresh_assignments()
        self._update_go_to_target_state()

    def refresh_tags(self) -> None:
        self.tags = self.service.search_tags(self.search_edit.text(), color_key=str(self.color_filter.currentData() or "All"), sort_by=self.sort_combo.currentText())
        self.tag_table.setRowCount(len(self.tags))
        for row_index, tag in enumerate(self.tags):
            values = [tag.name, tag.color_key, "Yes" if tag.is_default else "No", tag.updated_at]
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if col == 0:
                    item.setData(Qt.ItemDataRole.UserRole, tag.id)
                self.tag_table.setItem(row_index, col, item)
        self.tag_table.resizeColumnsToContents()

    def refresh_assignments(self) -> None:
        target_type = self.target_filter.currentText()
        self.assignments = self.service.list_tag_assignments(
            self.search_edit.text(),
            color_key=str(self.color_filter.currentData() or "All"),
            target_type=target_type,
            sort_by=self.sort_combo.currentText(),
        )
        self.assignment_table.setRowCount(len(self.assignments))
        for row_index, assignment in enumerate(self.assignments):
            values = [
                assignment.get("tag_name"),
                assignment.get("color_key"),
                assignment.get("target_type"),
                assignment.get("target_label") or assignment.get("object_ref"),
                assignment.get("audit_id"),
                assignment.get("machine_id"),
                assignment.get("field_label") or assignment.get("field_key"),
                assignment.get("comment"),
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value or ""))
                if col == 0:
                    item.setData(Qt.ItemDataRole.UserRole, assignment["assignment_id"])
                if col == 7:
                    item.setToolTip(str(value or ""))
                    item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
                self.assignment_table.setItem(row_index, col, item)
        self.assignment_table.resizeColumnsToContents()
        self.assignment_table.setColumnWidth(7, 260)
        self.assignment_table.resizeRowsToContents()
        self.status_label.setText(f"{len(self.tags)} tag(s), {len(self.assignments)} tagged target(s)")

    def load_selected_tag(self) -> None:
        selected = self.tag_table.selectedItems()
        if not selected:
            self._update_go_to_target_state()
            return
        row = selected[0].row()
        item = self.tag_table.item(row, 0)
        tag_id = item.data(Qt.ItemDataRole.UserRole) if item else None
        if not tag_id:
            self._update_go_to_target_state()
            return
        tag = self.service.get_tag(str(tag_id))
        self.selected_tag_id = tag.id
        self.assignment_table.clearSelection()
        self.name_edit.setText(tag.name)
        index = self.color_combo.findData(tag.color_key)
        if index >= 0:
            self.color_combo.setCurrentIndex(index)
        self.description_edit.setPlainText(tag.description or "")
        self._update_go_to_target_state()

    def new_tag(self) -> None:
        self.selected_tag_id = None
        self.name_edit.clear()
        self.color_combo.setCurrentIndex(0)
        self.description_edit.clear()
        self.status_label.setText("New tag ready.")

    def save_tag(self) -> None:
        try:
            if self.selected_tag_id:
                tag = self.service.update_tag(
                    self.selected_tag_id,
                    name=self.name_edit.text().strip(),
                    color_key=str(self.color_combo.currentData() or "yellow"),
                    description=self.description_edit.toPlainText().strip(),
                )
            else:
                tag = self.service.create_tag(
                    self.name_edit.text().strip(),
                    str(self.color_combo.currentData() or "yellow"),
                    description=self.description_edit.toPlainText().strip(),
                )
                self.selected_tag_id = tag.id
            self.refresh()
            self.status_label.setText(f"Saved tag: {tag.name}")
        except Exception as exc:
            QMessageBox.warning(self, "Save Tag", f"Could not save tag: {exc}")

    def archive_tag(self) -> None:
        if not self.selected_tag_id:
            return
        answer = QMessageBox.question(self, "Archive Tag", "Archive this tag definition? Existing assignment history stays in the database.")
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.service.archive_tag(self.selected_tag_id)
        self.new_tag()
        self.refresh()

    def selected_assignment(self) -> dict[str, object] | None:
        row = self.assignment_table.currentRow()
        if row < 0 or row >= len(getattr(self, "assignments", [])):
            return None
        return self.assignments[row]

    def go_to_target(self) -> None:
        assignment = self.selected_assignment()
        navigator = AnnotationTargetNavigator(self)
        if assignment is not None:
            navigator.open_target(assignment)
            return
        if not self.selected_tag_id:
            self.status_label.setText("Select a tagged target or tag first.")
            return
        targets = self.service.get_targets_for_tag(self.selected_tag_id)
        if not targets:
            self.status_label.setText("This tag is not assigned to any targets yet.")
            return
        navigator.open_targets(targets, title="Select Target for Tag")

    def select_tag_or_assignment(self, *, tag_id: str | None = None, assignment_id: str | None = None) -> None:
        self.refresh()
        if tag_id:
            for row in range(self.tag_table.rowCount()):
                item = self.tag_table.item(row, 0)
                if item and str(item.data(Qt.ItemDataRole.UserRole)) == str(tag_id):
                    self.tag_table.selectRow(row)
                    break
        if assignment_id:
            for row in range(self.assignment_table.rowCount()):
                item = self.assignment_table.item(row, 0)
                if item and str(item.data(Qt.ItemDataRole.UserRole)) == str(assignment_id):
                    self.assignment_table.selectRow(row)
                    self.assignment_table.scrollToItem(item)
                    break
        self._update_go_to_target_state()

    def _update_go_to_target_state(self) -> None:
        has_assignment = self.selected_assignment() is not None
        self.go_to_target_button.setEnabled(has_assignment or bool(self.selected_tag_id))

    def archive_selected_assignments(self) -> None:
        selected_rows = sorted({item.row() for item in self.assignment_table.selectedItems()})
        assignment_ids = []
        for row in selected_rows:
            item = self.assignment_table.item(row, 0)
            if item:
                assignment_ids.append(str(item.data(Qt.ItemDataRole.UserRole)))
        if not assignment_ids:
            return
        answer = QMessageBox.question(self, "Bulk Edit Tags", f"Archive {len(assignment_ids)} selected tag assignment(s)?")
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.service.archive_assignments(assignment_ids)
        self.refresh()

    def sync_colors(self) -> None:
        result = self.service.sync_all_tag_colors_to_workbook()
        warning_text = "; ".join(result.get("warnings", []))
        self.status_label.setText(f"Workbook color sync checked {result.get('synced_count', 0)} target(s). {warning_text}")

    def export_markdown(self) -> None:
        path = self.service.export_tags_markdown(self.assignments)
        self.status_label.setText(f"Exported Markdown: {path}")

    def export_excel(self) -> None:
        path = self.service.export_tags_excel(self.assignments)
        self.status_label.setText(f"Exported Excel: {path}")
