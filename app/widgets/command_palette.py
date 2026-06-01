from __future__ import annotations

try:
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtWidgets import (
        QComboBox,
        QDialog,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMessageBox,
        QPushButton,
        QTableWidget,
        QTableWidgetItem,
        QTabWidget,
        QVBoxLayout,
        QWidget,
    )
except ImportError:  # pragma: no cover
    Qt = QTimer = None
    QComboBox = QDialog = QHBoxLayout = QLabel = QLineEdit = QMessageBox = QPushButton = QTabWidget = QTableWidget = (
        QTableWidgetItem
    ) = QVBoxLayout = QWidget = None

from app.command_registry import CommandRegistry, CommandSpec
from app.task_runner import TaskRequest, get_task_manager
from core.search import SearchFilters, SearchResult, search_project, sqlite_fts_status


class CommandPalette(QDialog):
    COMMAND_COLUMNS = ["Command", "Category", "Writes Files", "Safety", "Status", "Context", "Description"]
    SEARCH_COLUMNS = ["Type", "Title", "Subtitle", "Audit ID", "Machine", "Status/Severity"]

    def __init__(
        self, registry: CommandRegistry, project_root: str, parent=None, *, current_page_key: str | None = None
    ):
        super().__init__(parent)
        self.registry = registry
        self.project_root = project_root
        self.current_page_key = current_page_key
        self.command_rows: list[CommandSpec] = []
        self.search_rows: list[SearchResult] = []
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(180)
        self._search_timer.timeout.connect(self.refresh_search)
        self._search_running = False
        self._search_pending = False
        self.setWindowTitle("Command Palette")
        self.resize(980, 620)

        layout = QVBoxLayout(self)
        self.query_edit = QLineEdit()
        self.query_edit.setPlaceholderText("Type a command or search audits, notes, tags, reports, machines...")
        self.query_edit.textChanged.connect(self.refresh)
        layout.addWidget(self.query_edit)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, stretch=1)

        command_tab = QVBoxLayout()
        command_container = _Container(command_tab)
        command_filter_row = QHBoxLayout()
        command_filter_row.addWidget(QLabel("Category"))
        self.command_category = QComboBox()
        self.command_category.addItem("All")
        self.command_category.addItems(self.registry.categories())
        self.command_category.currentTextChanged.connect(self.refresh_commands)
        command_filter_row.addWidget(self.command_category)
        self.current_page_button = QPushButton("Current Page")
        self.current_page_button.clicked.connect(self.show_current_page_commands)
        command_filter_row.addWidget(self.current_page_button)
        self.recent_button = QPushButton("Recent")
        self.recent_button.clicked.connect(self.show_recent_commands)
        command_filter_row.addWidget(self.recent_button)
        command_filter_row.addStretch(1)
        command_tab.addLayout(command_filter_row)
        self.command_table = QTableWidget(0, len(self.COMMAND_COLUMNS))
        self.command_table.setHorizontalHeaderLabels(self.COMMAND_COLUMNS)
        self.command_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.command_table.setAlternatingRowColors(True)
        self.command_table.itemDoubleClicked.connect(lambda _item: self.execute_selected_command())
        command_tab.addWidget(self.command_table, stretch=1)
        self.tabs.addTab(command_container, "Commands")

        search_tab = QVBoxLayout()
        search_container = _Container(search_tab)
        filter_row = QHBoxLayout()
        self.type_filter = QComboBox()
        self.type_filter.addItems(
            ["All", "audit", "machine", "note", "tag", "open_item", "validation", "report", "photo"]
        )
        self.audit_filter = QLineEdit()
        self.audit_filter.setPlaceholderText("Audit ID")
        self.machine_filter = QLineEdit()
        self.machine_filter.setPlaceholderText("Machine")
        self.tag_filter = QLineEdit()
        self.tag_filter.setPlaceholderText("Tag")
        self.status_filter = QLineEdit()
        self.status_filter.setPlaceholderText("Status")
        self.severity_filter = QLineEdit()
        self.severity_filter.setPlaceholderText("Severity")
        self.date_filter = QLineEdit()
        self.date_filter.setPlaceholderText("Date")
        self.due_filter = QLineEdit()
        self.due_filter.setPlaceholderText("Due date")
        for label, widget in [
            ("Type", self.type_filter),
            ("Audit", self.audit_filter),
            ("Machine", self.machine_filter),
            ("Tag", self.tag_filter),
            ("Status", self.status_filter),
            ("Severity", self.severity_filter),
            ("Date", self.date_filter),
            ("Due", self.due_filter),
        ]:
            filter_row.addWidget(QLabel(label))
            filter_row.addWidget(widget)
        filter_row.addStretch(1)
        search_tab.addLayout(filter_row)
        for widget in [
            self.type_filter,
            self.audit_filter,
            self.machine_filter,
            self.tag_filter,
            self.status_filter,
            self.severity_filter,
            self.date_filter,
            self.due_filter,
        ]:
            if isinstance(widget, QComboBox):
                widget.currentTextChanged.connect(self.schedule_search_refresh)
            else:
                widget.textChanged.connect(self.schedule_search_refresh)
        self.fts_label = QLabel()
        self.fts_label.setObjectName("MutedText")
        search_tab.addWidget(self.fts_label)
        self.search_table = QTableWidget(0, len(self.SEARCH_COLUMNS))
        self.search_table.setHorizontalHeaderLabels(self.SEARCH_COLUMNS)
        self.search_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.search_table.setAlternatingRowColors(True)
        self.search_table.itemDoubleClicked.connect(lambda _item: self.open_selected_result())
        search_tab.addWidget(self.search_table, stretch=1)
        self.tabs.addTab(search_container, "Search")

        button_row = QHBoxLayout()
        self.run_button = QPushButton("Run Command")
        self.run_button.clicked.connect(self.execute_selected_command)
        self.open_button = QPushButton("Open Result")
        self.open_button.clicked.connect(self.open_selected_result)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.reject)
        button_row.addWidget(self.run_button)
        button_row.addWidget(self.open_button)
        button_row.addStretch(1)
        button_row.addWidget(close_button)
        layout.addLayout(button_row)
        self.refresh_commands()
        self.fts_label.setText("Search will load after you type or choose a filter.")

    def refresh(self) -> None:
        self.refresh_commands()
        self.schedule_search_refresh()

    def refresh_commands(self) -> None:
        self.command_rows = self.registry.filter(
            self.query_edit.text(), category=self.command_category.currentText(), current_page_key=self.current_page_key
        )
        self._populate_command_table(self.command_rows)

    def show_current_page_commands(self) -> None:
        if not self.current_page_key:
            self.command_rows = []
        else:
            self.command_rows = [
                command
                for command in self.registry.filter(self.query_edit.text(), current_page_key=self.current_page_key)
                if command.is_context_command(self.current_page_key)
            ]
        self._populate_command_table(self.command_rows)

    def show_recent_commands(self) -> None:
        query = self.query_edit.text().casefold().strip()
        self.command_rows = [
            command
            for command in self.registry.recent_commands(limit=8)
            if not query or query in command.searchable_text()
        ]
        self._populate_command_table(self.command_rows)

    def _populate_command_table(self, rows: list[CommandSpec]) -> None:
        sorting = self.command_table.isSortingEnabled()
        self.command_table.setSortingEnabled(False)
        self.command_table.blockSignals(True)
        self.command_table.setUpdatesEnabled(False)
        try:
            self.command_table.setRowCount(len(rows))
            for row, command in enumerate(rows):
                status = "Enabled" if command.enabled else command.disabled_reason
                context = (
                    "Current page" if command.is_context_command(self.current_page_key) else (command.page_key or "")
                )
                values = [
                    command.display_name,
                    command.category,
                    "Yes" if command.writes_files else "No",
                    command.safety_level,
                    status,
                    context,
                    command.description,
                ]
                for col, value in enumerate(values):
                    item = QTableWidgetItem(str(value or ""))
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    if col == 0:
                        item.setData(Qt.ItemDataRole.UserRole, command.command_id)
                    if command.writes_files and col == 2:
                        item.setToolTip("This command can write local project files.")
                    if not command.enabled:
                        item.setToolTip(command.disabled_reason)
                    self.command_table.setItem(row, col, item)
            self.command_table.resizeColumnsToContents()
        finally:
            self.command_table.setUpdatesEnabled(True)
            self.command_table.blockSignals(False)
            self.command_table.setSortingEnabled(sorting)
        if rows:
            self.command_table.selectRow(0)

    def schedule_search_refresh(self, *_args) -> None:
        self._search_timer.start()

    def refresh_search(self) -> None:
        filters = self._search_filters()
        query = self.query_edit.text().strip()
        if not query and not _has_search_filters(filters):
            self.search_rows = []
            self._populate_search_table([])
            self.fts_label.setText("Search will load after you type or choose a filter.")
            return
        if self._search_running:
            self._search_pending = True
            return
        self._search_running = True
        self.fts_label.setText("Searching in background...")

        def _load() -> tuple[list[SearchResult], dict]:
            return search_project(self.project_root, query, filters, limit=80), sqlite_fts_status(self.project_root)

        def _finished(task_result) -> None:
            self._search_running = False
            if task_result.ok:
                rows, fts = task_result.result_data
                self.search_rows = rows
                self._populate_search_table(rows)
                self.fts_label.setText(f"Search mode: {fts.get('mode', 'like_fallback')} - {fts.get('reason', '')}")
            else:
                self.fts_label.setText(f"Search failed: {task_result.error or task_result.message}")
            if self._search_pending:
                self._search_pending = False
                self.schedule_search_refresh()

        accepted = get_task_manager().run_task(
            TaskRequest(id="command_palette_search", name="Command Palette Search", category="search", callable=_load),
            on_finished=_finished,
        )
        if not accepted:
            self._search_running = False

    def _search_filters(self) -> SearchFilters:
        type_text = self.type_filter.currentText()
        return SearchFilters(
            result_types=() if type_text == "All" else (type_text,),
            audit_id=self.audit_filter.text().strip(),
            machine=self.machine_filter.text().strip(),
            tag=self.tag_filter.text().strip(),
            status=self.status_filter.text().strip(),
            severity=self.severity_filter.text().strip(),
            date=self.date_filter.text().strip(),
            due_date=self.due_filter.text().strip(),
        )

    def _populate_search_table(self, rows: list[SearchResult]) -> None:
        sorting = self.search_table.isSortingEnabled()
        self.search_table.setSortingEnabled(False)
        self.search_table.blockSignals(True)
        self.search_table.setUpdatesEnabled(False)
        try:
            self.search_table.setRowCount(len(rows))
            for row, result in enumerate(rows):
                status_or_severity = result.metadata.get("severity") or result.metadata.get("status") or ""
                values = [
                    result.result_type,
                    result.title,
                    result.subtitle,
                    result.audit_id,
                    result.machine,
                    status_or_severity,
                ]
                for col, value in enumerate(values):
                    item = QTableWidgetItem(str(value or ""))
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    if col == 0:
                        item.setData(Qt.ItemDataRole.UserRole, result)
                    self.search_table.setItem(row, col, item)
            self.search_table.resizeColumnsToContents()
        finally:
            self.search_table.setUpdatesEnabled(True)
            self.search_table.blockSignals(False)
            self.search_table.setSortingEnabled(sorting)
        if rows:
            self.search_table.selectRow(0)

    def execute_selected_command(self) -> bool:
        row = self.command_table.currentRow()
        if row < 0 or row >= len(self.command_rows):
            return False
        command = self.command_rows[row]
        if not command.enabled:
            if QMessageBox is not None:
                QMessageBox.information(
                    self, "Command Unavailable", command.disabled_reason or "This command is unavailable."
                )
            return False
        if command.requires_confirmation and not self._confirm_command(command):
            return False
        ok = self.registry.execute(command.command_id)
        if ok:
            self.accept()
        return ok

    def open_selected_result(self) -> bool:
        row = self.search_table.currentRow()
        if row < 0 or row >= len(self.search_rows):
            return False
        result = self.search_rows[row]
        window = self.parent()
        if hasattr(window, "open_search_result"):
            ok = bool(window.open_search_result(result))
            if ok:
                self.accept()
            return ok
        return False

    def _confirm_command(self, command: CommandSpec) -> bool:
        if QMessageBox is None:
            return True
        answer = QMessageBox.question(
            self,
            "Confirm Command",
            f"{command.display_name} may modify local project files. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes


class _Container(QWidget):
    def __init__(self, layout):
        super().__init__()
        self.setLayout(layout)


def _has_search_filters(filters: SearchFilters) -> bool:
    return bool(
        filters.result_types
        or filters.audit_id
        or filters.machine
        or filters.tag
        or filters.status
        or filters.severity
        or filters.date
        or filters.due_date
    )
