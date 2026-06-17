from __future__ import annotations

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import (
        QComboBox,
        QHBoxLayout,
        QLabel,
        QPushButton,
        QSplitter,
        QTableWidget,
        QTableWidgetItem,
        QVBoxLayout,
        QWidget,
    )
except ImportError:  # pragma: no cover
    Qt = None
    QComboBox = QHBoxLayout = QLabel = QPushButton = QSplitter = QTableWidget = QTableWidgetItem = QVBoxLayout = (
        QWidget
    ) = None

from app.page_tasks import run_tool_background
from app.widgets.annotation_target_navigator import AnnotationTargetNavigator
from app.widgets.tool_run_panel import ToolRunPanel
from core.compatibility_matrix import (
    COLUMN_MODE_PART_FAMILY,
    COLUMN_MODE_SOURCE_AUDIT,
    COLUMN_MODE_TOOL,
    CompatibilityMatrixCell,
    CompatibilityMatrixSummary,
    build_compatibility_matrix,
    export_compatibility_matrix,
)


class CompatibilityMatrixPage(QWidget):
    DETAIL_COLUMNS = [
        "Field",
        "Value",
    ]

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.summary: CompatibilityMatrixSummary | None = None
        self.navigator = AnnotationTargetNavigator(self)

        layout = QVBoxLayout(self)
        heading = QLabel("Compatibility Matrix")
        heading.setStyleSheet("font-size: 18pt; font-weight: 600;")
        layout.addWidget(heading)

        controls = QHBoxLayout()
        self.column_mode_combo = QComboBox()
        self.column_mode_combo.addItem("Tools", COLUMN_MODE_TOOL)
        self.column_mode_combo.addItem("Part Families", COLUMN_MODE_PART_FAMILY)
        self.column_mode_combo.addItem("Source Audits", COLUMN_MODE_SOURCE_AUDIT)
        controls.addWidget(QLabel("Columns"))
        controls.addWidget(self.column_mode_combo)
        for label, callback in [
            ("Refresh", self.refresh_data),
            ("Export Matrix", self.export_matrix),
            ("Open Audit", self.open_selected_audit),
            ("Open Machine 360", self.open_selected_machine_360),
        ]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            controls.addWidget(button)
        controls.addStretch(1)
        layout.addLayout(controls)

        splitter = QSplitter()
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(QLabel("Machines x compatibility columns"))
        self.matrix_table = QTableWidget()
        self.matrix_table.setAlternatingRowColors(True)
        self.matrix_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectItems)
        self.matrix_table.itemSelectionChanged.connect(self.populate_details)
        left_layout.addWidget(self.matrix_table)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.addWidget(QLabel("Selected cell details"))
        self.details_table = QTableWidget(0, len(self.DETAIL_COLUMNS))
        self.details_table.setHorizontalHeaderLabels(self.DETAIL_COLUMNS)
        self.details_table.setAlternatingRowColors(True)
        right_layout.addWidget(self.details_table)
        self.result_panel = ToolRunPanel()
        right_layout.addWidget(self.result_panel)
        splitter.addWidget(right)
        splitter.setSizes([760, 460])
        layout.addWidget(splitter, stretch=1)

        self.refresh_data()

    def refresh_data(self) -> None:
        mode = self.column_mode_combo.currentData() or COLUMN_MODE_TOOL
        self.summary = build_compatibility_matrix(self.config.project_root, column_mode=mode)
        self._populate_matrix()
        self.result_panel.show_text(
            f"Loaded {len(self.summary.machines)} machine(s), {len(self.summary.columns)} column(s), "
            f"{self.summary.metrics.get('conflict_cells', 0)} conflict cell(s), "
            f"{self.summary.metrics.get('needs_review_cells', 0)} needs-review cell(s)."
        )

    def export_matrix(self) -> None:
        mode = self.column_mode_combo.currentData() or COLUMN_MODE_TOOL
        run_tool_background(
            self.result_panel,
            "compatibility_matrix_export",
            "Compatibility Matrix Export",
            lambda: export_compatibility_matrix(self.config.project_root, column_mode=mode),
            lambda _result: None,
            modifies_files=True,
        )

    def populate_details(self) -> None:
        cell = self.selected_cell()
        rows = []
        if cell is not None:
            rows = [
                {"Field": "Machine", "Value": cell.machine},
                {"Field": "Column", "Value": cell.column_label},
                {"Field": "Status", "Value": cell.compatibility_status},
                {"Field": "Source Audit ID", "Value": cell.source_audit_id},
                {"Field": "Audit Context", "Value": cell.audit_context},
                {"Field": "Compatibility Source", "Value": cell.compatibility_source},
                {"Field": "Physical Audit Verified", "Value": cell.physical_audit_verified},
                {"Field": "Compatibility Confidence", "Value": cell.compatibility_confidence},
                {"Field": "Physical Audit IDs", "Value": "; ".join(cell.physical_audit_ids)},
                {"Field": "Compatibility Audit IDs", "Value": "; ".join(cell.compatibility_audit_ids)},
                {"Field": "Fields Copied", "Value": "; ".join(cell.fields_copied)},
                {"Field": "Conflicts", "Value": "; ".join(cell.conflicts)},
                {"Field": "Missing Data", "Value": "; ".join(cell.missing_data)},
                {"Field": "Recommended Action", "Value": cell.recommended_action},
            ]
        self.details_table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            for column_index, column in enumerate(self.DETAIL_COLUMNS):
                self.details_table.setItem(row_index, column_index, QTableWidgetItem(str(row.get(column, ""))))
        self.details_table.resizeColumnsToContents()

    def open_selected_audit(self) -> None:
        cell = self.selected_cell()
        if cell is None:
            self.result_panel.show_text("Select a compatibility cell first.")
            return
        audit_id = next(iter([*cell.physical_audit_ids, *cell.compatibility_audit_ids, cell.source_audit_id]), "")
        if not audit_id:
            self.result_panel.show_text("Selected cell has no audit row to open.")
            return
        self.navigator.open_target({"target_type": "audit", "audit_id": audit_id, "machine_id": cell.machine})

    def open_selected_machine_360(self) -> None:
        cell = self.selected_cell()
        machine = cell.machine if cell is not None else self._selected_machine()
        if not machine:
            self.result_panel.show_text("Select a machine row first.")
            return
        window = self.window() if hasattr(self, "window") else None
        if hasattr(window, "_navigate_to_page"):
            window._navigate_to_page("machine_360")
            page = getattr(window, "pages", {}).get("machine_360")
            if hasattr(page, "select_machine"):
                page.select_machine(machine)
            return
        self.result_panel.show_text(f"Machine 360 target: {machine}")

    def selected_cell(self) -> CompatibilityMatrixCell | None:
        if self.summary is None:
            return None
        row_index = self.matrix_table.currentRow()
        column_index = self.matrix_table.currentColumn()
        if row_index < 0 or column_index <= 0 or row_index >= len(self.summary.rows):
            return None
        cell_index = column_index - 1
        row = self.summary.rows[row_index]
        if cell_index >= len(row.cells):
            return None
        return row.cells[cell_index]

    def _selected_machine(self) -> str:
        row_index = self.matrix_table.currentRow()
        if self.summary is None or row_index < 0 or row_index >= len(self.summary.rows):
            return ""
        return self.summary.rows[row_index].machine

    def _populate_matrix(self) -> None:
        if self.summary is None:
            return
        headers = ["Machine", *[column.label for column in self.summary.columns]]
        self.matrix_table.setColumnCount(len(headers))
        self.matrix_table.setHorizontalHeaderLabels(headers)
        self.matrix_table.setRowCount(len(self.summary.rows))
        for row_index, row in enumerate(self.summary.rows):
            self.matrix_table.setItem(row_index, 0, QTableWidgetItem(row.machine))
            for column_index, cell in enumerate(row.cells, start=1):
                item = QTableWidgetItem(cell.compatibility_status)
                item.setToolTip(cell.recommended_action)
                if Qt is not None:
                    item.setData(Qt.ItemDataRole.UserRole, cell)
                self.matrix_table.setItem(row_index, column_index, item)
        self.matrix_table.resizeColumnsToContents()
        if self.summary.rows and self.summary.columns:
            self.matrix_table.setCurrentCell(0, 1)
        self.populate_details()
