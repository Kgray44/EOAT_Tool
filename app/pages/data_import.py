from __future__ import annotations

try:
    from PySide6.QtWidgets import (
        QComboBox,
        QFileDialog,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QPushButton,
        QTableWidget,
        QTableWidgetItem,
        QVBoxLayout,
        QWidget,
    )
except ImportError:  # pragma: no cover
    QFileDialog = QComboBox = QHBoxLayout = QLabel = QLineEdit = QPushButton = QTableWidget = QTableWidgetItem = QVBoxLayout = QWidget = None

from app.widgets.report_viewer import ReportViewer
from app.widgets.tool_run_panel import ToolRunPanel
from core.data_import import confirm_import, dry_run_import, preview_import_file, supported_import_types


class DataImportPage(QWidget):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        layout = QVBoxLayout(self)
        heading = QLabel("Data Import")
        heading.setStyleSheet("font-size: 18pt; font-weight: 600;")
        layout.addWidget(heading)

        controls = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("CSV, TSV, or XLSX import file")
        self.type_combo = QComboBox()
        self.type_combo.addItem("Auto-detect", "")
        for spec in supported_import_types():
            self.type_combo.addItem(spec.label, spec.type_id)
        for label, callback in [
            ("Browse", self.browse),
            ("Preview", self.preview_file),
            ("Dry Run", self.dry_run),
            ("Confirm Import", self.confirm),
        ]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            controls.addWidget(button)
        layout.addWidget(self.path_edit)
        layout.addWidget(self.type_combo)
        layout.addLayout(controls)

        self.table = QTableWidget()
        layout.addWidget(self.table, stretch=2)
        self.preview = ReportViewer()
        layout.addWidget(self.preview, stretch=1)
        self.result_panel = ToolRunPanel()
        layout.addWidget(self.result_panel, stretch=1)

    def browse(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(self, "Select import file", "", "Data Files (*.csv *.tsv *.txt *.xlsx *.xlsm);;All Files (*)")
        if path:
            self.path_edit.setText(path)

    def _selected_type(self) -> str | None:
        value = self.type_combo.currentData()
        return str(value) if value else None

    def preview_file(self) -> None:
        try:
            preview = preview_import_file(self.path_edit.text().strip(), import_type=self._selected_type())
            self._populate(preview.preview_rows)
            self.preview.show_markdown_text(
                "\n".join(
                    [
                        "# Import Preview",
                        "",
                        f"- Type: {preview.import_label}",
                        f"- Rows: {preview.row_count}",
                        f"- Headers: {', '.join(preview.headers)}",
                        f"- Mapping: {preview.mapping}",
                    ]
                )
            )
            self.result_panel.show_text("Preview loaded. No files were written.")
        except Exception as exc:
            self.result_panel.show_text(f"Preview failed: {exc}")

    def dry_run(self) -> None:
        try:
            dry_run = dry_run_import(self.config.project_root, self.path_edit.text().strip(), import_type=self._selected_type())
            self._populate(dry_run.mapped_rows)
            self.preview.show_markdown_text(
                "\n".join(
                    [
                        "# Import Dry Run",
                        "",
                        f"- Type: {dry_run.import_label}",
                        f"- Rows: {dry_run.row_count}",
                        f"- Validation issues: {len(dry_run.issues)}",
                        "",
                        "## Would Write",
                        *[f"- {path}" for path in dry_run.would_write],
                    ]
                )
            )
            self.result_panel.show_text("Dry run complete. No files were written.")
        except Exception as exc:
            self.result_panel.show_text(f"Dry run failed: {exc}")

    def confirm(self) -> None:
        result = confirm_import(self.config.project_root, self.path_edit.text().strip(), import_type=self._selected_type(), confirmed=True)
        self.result_panel.show_result(result)

    def _populate(self, rows) -> None:
        rows = list(rows)
        columns = sorted({key for row in rows for key in row.keys()})
        self.table.setColumnCount(len(columns))
        self.table.setHorizontalHeaderLabels(columns)
        self.table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            for col_index, column in enumerate(columns):
                self.table.setItem(row_index, col_index, QTableWidgetItem(str(row.get(column, ""))))
        self.table.resizeColumnsToContents()
