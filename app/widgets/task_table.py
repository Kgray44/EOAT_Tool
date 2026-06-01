from __future__ import annotations

try:
    from PySide6.QtWidgets import QTableWidget, QTableWidgetItem
except ImportError:  # pragma: no cover
    QTableWidget = QTableWidgetItem = None


class TaskTable(QTableWidget):
    def set_rows(self, headers: list[str], rows: list[list[str]]) -> None:
        self.setColumnCount(len(headers))
        self.setHorizontalHeaderLabels(headers)
        self.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            for col_index, value in enumerate(row):
                self.setItem(row_index, col_index, QTableWidgetItem(str(value)))
        self.resizeColumnsToContents()
