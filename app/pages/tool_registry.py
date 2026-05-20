from __future__ import annotations

try:
    from PySide6.QtWidgets import QLabel, QLineEdit, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget
except ImportError:  # pragma: no cover
    QLabel = QLineEdit = QTableWidget = QTableWidgetItem = QVBoxLayout = QWidget = None

from core.tool_registry import ToolRegistry


class ToolRegistryPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        heading = QLabel("Tool Registry")
        heading.setStyleSheet("font-size: 18pt; font-weight: 600;")
        layout.addWidget(heading)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter by tool name, category, phase, status, or CLI module")
        self.search.textChanged.connect(self.populate)
        layout.addWidget(self.search)
        self.table = QTableWidget()
        layout.addWidget(self.table)
        self.populate()

    def populate(self) -> None:
        registry = ToolRegistry.load()
        query = self.search.text().strip().lower() if hasattr(self, "search") else ""
        headers = [
            "Name",
            "Category",
            "Phase",
            "Status",
            "Dashboard page",
            "CLI module",
            "Safe repeat?",
            "Modifies files?",
            "Requires workbook?",
            "Requires Git?",
        ]
        tools = [
            tool for tool in registry.list_tools()
            if not query or query in " ".join(str(value) for value in tool.to_dict().values()).lower()
        ]
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.setRowCount(len(tools))
        for row, tool in enumerate(tools):
            values = [
                tool.name,
                tool.category,
                tool.phase,
                tool.implementation_status,
                tool.dashboard_page,
                tool.cli_module,
                "Yes" if tool.safe_to_run_repeatedly else "No",
                "Yes" if tool.modifies_project_files else "No",
                "Yes" if tool.requires_workbook else "No",
                "Yes" if tool.requires_git else "No",
            ]
            for col, value in enumerate(values):
                self.table.setItem(row, col, QTableWidgetItem(str(value)))
        self.table.resizeColumnsToContents()
