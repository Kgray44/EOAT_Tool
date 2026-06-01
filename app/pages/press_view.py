from __future__ import annotations

import time

try:
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtWidgets import (
        QComboBox,
        QGridLayout,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QPushButton,
        QSplitter,
        QTableWidget,
        QTableWidgetItem,
        QVBoxLayout,
        QWidget,
    )
except ImportError:  # pragma: no cover
    Qt = QTimer = None
    QComboBox = QGridLayout = QHBoxLayout = QLabel = QLineEdit = QPushButton = QSplitter = QTableWidget = (
        QTableWidgetItem
    ) = QVBoxLayout = QWidget = None

from app.event_bus import EVENT_AUDIT_SAVED
from app.page_async import AsyncRefreshMixin, log_page_performance
from app.widgets.annotation_target_navigator import AnnotationTargetNavigator
from app.widgets.status_card import StatusCard
from app.widgets.tool_run_panel import ToolRunPanel
from core.performance import log_performance
from core.press_view import (
    PressAuditEntry,
    PressViewGroup,
    build_press_view_groups,
    export_press_summary,
    load_cached_press_view_groups,
    save_press_view_cache,
)


class PressViewPage(AsyncRefreshMixin, QWidget):
    GROUP_COLUMNS = [
        "Press/Machine",
        "Physical",
        "Compatible Assigned Here",
        "Linked Compatible Machines",
        "Family Machines",
        "Tools",
        "Open Items",
        "Validation",
        "Photos",
        "Compliance",
        "Worst Standard",
        "Pilot",
        "Last Updated",
    ]
    ENTRY_COLUMNS = ["Audit ID", "Entry Type", "Tool", "EOAT Type", "Status", "Source Audit", "Known Issues"]

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self._init_async_refresh("press_view")
        self.all_groups: list[PressViewGroup] = []
        self.groups: list[PressViewGroup] = []
        self.current_entries: list[PressAuditEntry] = []
        self.navigator = AnnotationTargetNavigator(self)
        self._filter_timer = QTimer(self) if QTimer is not None else None
        if self._filter_timer is not None:
            self._filter_timer.setSingleShot(True)
            self._filter_timer.setInterval(150)
            self._filter_timer.timeout.connect(self.apply_filters)
        self._last_on_show_at = 0.0

        layout = QVBoxLayout(self)
        heading = QLabel("Press View")
        heading.setStyleSheet("font-size: 18pt; font-weight: 600;")
        layout.addWidget(heading)

        controls = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search press, audit ID, tool, EOAT type, issue...")
        self.search_edit.textChanged.connect(self._schedule_filter)
        self.status_filter = QComboBox()
        self.status_filter.addItems(["All"])
        self.status_filter.currentTextChanged.connect(self.apply_filters)
        for label, widget in [("Search", self.search_edit), ("Status", self.status_filter)]:
            controls.addWidget(QLabel(label))
            controls.addWidget(widget)
        self.reload_cache_button = QPushButton("Reload Cache")
        self.reload_cache_button.clicked.connect(lambda: self.reload_cache(force=True))
        self.deep_rebuild_button = QPushButton("Deep Rebuild Press View")
        self.deep_rebuild_button.clicked.connect(lambda: self.deep_rebuild(force=True))
        for button in [self.reload_cache_button, self.deep_rebuild_button]:
            controls.addWidget(button)
        for label, callback in [
            ("Auto Size Columns", self.auto_size_columns),
            ("Open Audit", self.open_selected_audit),
            ("Open Machine Group", self.open_machine_group),
            ("Export Press Summary", self.export_selected_press_summary),
        ]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            controls.addWidget(button)
        controls.addStretch(1)
        layout.addLayout(controls)

        card_grid = QGridLayout()
        self.cards: dict[str, StatusCard] = {}
        for index, name in enumerate(
            [
                "Press Groups",
                "Physical Audits",
                "Compatible Assigned Here",
                "Links From Source",
                "Open Items",
                "Validation Warnings",
                "Indexed Photos",
                "Avg Compliance",
            ]
        ):
            card = StatusCard(name)
            self.cards[name] = card
            card_grid.addWidget(card, index // 6, index % 6)
        layout.addLayout(card_grid)

        splitter = QSplitter()
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(QLabel("Press / machine groups"))
        self.group_table = QTableWidget(0, len(self.GROUP_COLUMNS))
        self.group_table.setHorizontalHeaderLabels(self.GROUP_COLUMNS)
        self.group_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.group_table.setAlternatingRowColors(True)
        self.group_table.itemSelectionChanged.connect(self.populate_entries)
        self._apply_default_table_widths(self.group_table)
        left_layout.addWidget(self.group_table)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.addWidget(QLabel("Physical audits"))
        self.physical_table = QTableWidget(0, len(self.ENTRY_COLUMNS))
        self.physical_table.setHorizontalHeaderLabels(self.ENTRY_COLUMNS)
        self.physical_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.physical_table.setAlternatingRowColors(True)
        self.physical_table.itemSelectionChanged.connect(lambda: self._entry_selection_changed(self.physical_table))
        self._apply_default_table_widths(self.physical_table)
        right_layout.addWidget(self.physical_table)
        right_layout.addWidget(QLabel("Compatible entries assigned to this machine"))
        self.compatible_table = QTableWidget(0, len(self.ENTRY_COLUMNS))
        self.compatible_table.setHorizontalHeaderLabels(self.ENTRY_COLUMNS)
        self.compatible_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.compatible_table.setAlternatingRowColors(True)
        self.compatible_table.itemSelectionChanged.connect(lambda: self._entry_selection_changed(self.compatible_table))
        self._apply_default_table_widths(self.compatible_table)
        right_layout.addWidget(self.compatible_table)
        right_layout.addWidget(QLabel("Compatible entries from this machine's source audits"))
        self.linked_compatible_table = QTableWidget(0, len(self.ENTRY_COLUMNS))
        self.linked_compatible_table.setHorizontalHeaderLabels(self.ENTRY_COLUMNS)
        self.linked_compatible_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.linked_compatible_table.setAlternatingRowColors(True)
        self.linked_compatible_table.itemSelectionChanged.connect(
            lambda: self._entry_selection_changed(self.linked_compatible_table)
        )
        self._apply_default_table_widths(self.linked_compatible_table)
        right_layout.addWidget(self.linked_compatible_table)
        splitter.addWidget(right)
        splitter.setSizes([430, 760])
        layout.addWidget(splitter, stretch=1)

        self.result_panel = ToolRunPanel()
        layout.addWidget(self.result_panel, stretch=1)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.on_show()

    def refresh(self, *_args, force: bool = False) -> bool:
        return self.deep_rebuild(force=force)

    def deep_rebuild(self, *_args, force: bool = False) -> bool:
        def _load() -> dict:
            started = time.perf_counter()
            groups = build_press_view_groups(self.config.project_root)
            save_press_view_cache(self.config.project_root, groups)
            log_performance(
                self.config.project_root,
                "press_view.background_rebuild",
                time.perf_counter() - started,
                source="press_view",
                page_tool="press_view",
                details={"group_count": len(groups)},
            )
            return {
                "groups": groups,
                "source_counts": {
                    "groups": len(groups),
                    "physical": sum(len(group.physical_audits) for group in groups),
                    "compatible": sum(len(group.compatible_entries) for group in groups),
                    "linked_compatible": sum(len(group.linked_compatible_entries) for group in groups),
                },
                "cached": False,
            }

        return self._begin_background_refresh(
            task_id="press_view_deep_rebuild",
            name="Deep Rebuild Press View",
            load=_load,
            apply_result=self._apply_refresh_result,
            button=self.deep_rebuild_button,
            force=force,
            loading_text=self._loading_text(),
        )

    def reload_cache(self, *_args, force: bool = False) -> bool:
        self._show_cached_groups()
        return True

    def apply_filters(self, *_args) -> None:
        status = self.status_filter.currentText()
        query = self.search_edit.text().strip()
        self.groups = [
            group
            for group in self.all_groups
            if (
                status in {"", "All"}
                or any(status.casefold() in entry.status.casefold() for entry in self._filter_entries(group))
            )
            and (not query or self._matches_group_query(group, query))
        ]
        self._refresh_status_filter()
        self._populate_group_table()
        self._refresh_cards()
        if self.groups:
            self.group_table.selectRow(0)
        else:
            self._populate_entry_table(self.physical_table, [])
            self._populate_entry_table(self.compatible_table, [])
            self._populate_entry_table(self.linked_compatible_table, [])
            self.result_panel.show_text("No press/machine audit rows matched the current filters.")

    def _schedule_filter(self, *_args) -> None:
        if self._filter_timer is None:
            self.apply_filters()
            return
        self._filter_timer.start()

    def refresh_data(self) -> None:
        self.reload_cache()

    def on_show(self) -> None:
        now = time.monotonic()
        if now - self._last_on_show_at < 0.2:
            return True
        self._last_on_show_at = now
        started = time.perf_counter()
        self._show_cached_groups()
        log_page_performance(
            self.config.project_root,
            "press_view",
            "cached_show",
            time.perf_counter() - started,
            details={"row_count": len(self.all_groups), "cached_only": True},
        )
        return True

    def on_event(self, event) -> None:
        if getattr(event, "event_type", "") == EVENT_AUDIT_SAVED:
            self.result_panel.show_text(
                "Audit saved. Press View is marked stale; use Reload Cache for cached data or Deep Rebuild Press View for a full rebuild."
            )
            return True
        self.result_panel.show_text(
            "Press View cache may be stale; use Reload Cache for cached data or Deep Rebuild Press View for a full rebuild."
        )
        return True

    def on_project_root_changed(self, config) -> None:
        self.config = config
        self.all_groups = []
        self.groups = []
        self._populate_group_table()
        self._show_cached_groups()

    def select_machine(self, machine: str) -> bool:
        target = str(machine or "").strip().casefold()
        for row, group in enumerate(self.groups):
            if group.machine.casefold() == target or group.display_name.casefold() == target:
                self.group_table.selectRow(row)
                self.populate_entries()
                return True
        self.search_edit.setText(machine)
        for row, group in enumerate(self.groups):
            if target in group.machine.casefold() or target in group.display_name.casefold():
                self.group_table.selectRow(row)
                self.populate_entries()
                return True
        return False

    def selected_group(self) -> PressViewGroup | None:
        row = self.group_table.currentRow()
        if 0 <= row < len(self.groups):
            return self.groups[row]
        return None

    def selected_entry(self) -> PressAuditEntry | None:
        group = self.selected_group()
        if group is None:
            return None
        for table, entries in [
            (self.physical_table, group.physical_audits),
            (self.compatible_table, group.compatible_entries),
            (self.linked_compatible_table, group.linked_compatible_entries),
        ]:
            if not table.selectionModel().selectedRows():
                continue
            row = table.currentRow()
            if 0 <= row < len(entries):
                return entries[row]
        if group and group.physical_audits:
            return group.physical_audits[0]
        if group and group.compatible_entries:
            return group.compatible_entries[0]
        if group and group.linked_compatible_entries:
            return group.linked_compatible_entries[0]
        return None

    def _show_cached_groups(self) -> None:
        started = time.perf_counter()
        groups, generated_at, warning = load_cached_press_view_groups(self.config.project_root)
        log_performance(
            self.config.project_root,
            "press_view.cached_load",
            time.perf_counter() - started,
            source="press_view",
            page_tool="press_view",
            details={"cache_status": "hit" if groups else "miss", "group_count": len(groups)},
        )
        if not groups:
            self.all_groups = []
            self.groups = []
            self._populate_group_table()
            self._populate_entry_table(self.physical_table, [])
            self._populate_entry_table(self.compatible_table, [])
            self._populate_entry_table(self.linked_compatible_table, [])
            self._refresh_cards()
            message = "No cached Press View found. Click Deep Rebuild Press View to generate it."
            if warning and warning != "No cached press view found.":
                message = f"{warning} Click Deep Rebuild Press View to generate it."
            self.result_panel.show_text(message)
            return
        render_started = time.perf_counter()
        self.all_groups = groups
        self.apply_filters()
        render_seconds = time.perf_counter() - render_started
        log_performance(
            self.config.project_root,
            "press_view.render",
            render_seconds,
            source="press_view",
            page_tool="press_view",
            details={"row_count": len(self.groups), "cached": True},
        )
        self.result_panel.show_text(f"Showing cached press data from {_time_label(generated_at)}.")

    def _loading_text(self) -> str:
        if self.all_groups:
            return "Showing cached press data. Deep rebuilding Press View in background..."
        return "Deep rebuilding Press View in background..."

    def _apply_refresh_result(self, payload: dict, data_load_seconds: float) -> None:
        render_started = time.perf_counter()
        self.all_groups = list(payload.get("groups") or [])
        self.apply_filters()
        render_seconds = time.perf_counter() - render_started
        source_counts = dict(payload.get("source_counts") or {})
        log_page_performance(
            self.config.project_root,
            "press_view",
            "data_load",
            data_load_seconds,
            details={"row_count": len(self.all_groups), "source_counts": source_counts},
        )
        log_page_performance(
            self.config.project_root,
            "press_view",
            "table_render",
            render_seconds,
            details={"row_count": len(self.groups), "source_counts": source_counts},
        )
        log_performance(
            self.config.project_root,
            "press_view.render",
            render_seconds,
            source="press_view",
            page_tool="press_view",
            details={
                "row_count": len(self.groups),
                "source_counts": source_counts,
                "cached": bool(payload.get("cached")),
            },
        )
        if payload.get("cached"):
            self.result_panel.show_text(f"Loaded {len(self.groups)} cached press group(s) in {data_load_seconds:.1f}s.")
        else:
            self.result_panel.show_text(f"Deep rebuilt {len(self.groups)} press group(s) in {data_load_seconds:.1f}s.")

    def populate_entries(self) -> None:
        group = self.selected_group()
        if group is None:
            return
        self._populate_entry_table(self.physical_table, group.physical_audits)
        self._populate_entry_table(self.compatible_table, group.compatible_entries)
        self._populate_entry_table(self.linked_compatible_table, group.linked_compatible_entries)
        self.result_panel.show_text(
            f"{group.display_name}: {len(group.physical_audits)} physical audit(s), "
            f"{_count_phrase(len(group.compatible_entries), 'compatible entry', 'compatible entries')} assigned to this machine, "
            f"{_count_phrase(len(group.linked_compatible_entries), 'compatible machine link', 'compatible machine links')} from this machine's source audits, "
            f"{group.open_item_count} open item(s)."
        )

    def open_selected_audit(self) -> None:
        entry = self.selected_entry()
        if entry is None or not entry.audit_id:
            self.result_panel.show_text("Select an audit entry first.")
            return
        self.navigator.open_target({"target_type": "audit", "audit_id": entry.audit_id, "machine_id": entry.machine})

    def open_machine_group(self) -> None:
        group = self.selected_group()
        if group is None:
            self.result_panel.show_text("Select a press/machine group first.")
            return
        self.result_panel.show_text(
            f"Opened {group.display_name}. Use the audit tables to jump into physical, assigned compatible, or linked compatible entries."
        )

    def export_selected_press_summary(self) -> None:
        group = self.selected_group()
        if group is None:
            self.result_panel.show_text("Select a press/machine group first.")
            return
        result = export_press_summary(self.config.project_root, group.machine)
        self.result_panel.show_result(result)

    def _refresh_status_filter(self) -> None:
        current = self.status_filter.currentText()
        statuses = sorted(
            {entry.status for group in self.all_groups for entry in self._filter_entries(group) if entry.status},
            key=str.casefold,
        )
        self.status_filter.blockSignals(True)
        self.status_filter.clear()
        self.status_filter.addItem("All")
        self.status_filter.addItems(statuses)
        index = self.status_filter.findText(current)
        self.status_filter.setCurrentIndex(index if index >= 0 else 0)
        self.status_filter.blockSignals(False)

    def _populate_group_table(self) -> None:
        sorting = self.group_table.isSortingEnabled()
        self.group_table.setSortingEnabled(False)
        self.group_table.blockSignals(True)
        self.group_table.setUpdatesEnabled(False)
        try:
            self.group_table.setRowCount(len(self.groups))
            for row, group in enumerate(self.groups):
                values = [
                    group.display_name,
                    len(group.physical_audits),
                    len(group.compatible_entries),
                    len(group.linked_compatible_entries),
                    group.compatibility_family_machine_count,
                    ", ".join(group.tools),
                    group.open_item_count,
                    group.validation_warning_count,
                    group.photo_count,
                    group.average_compliance_score,
                    group.worst_compliance_category,
                    group.pilot_candidacy,
                    group.last_updated,
                ]
                for col, value in enumerate(values):
                    item = QTableWidgetItem(str(value or ""))
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    if col == 0:
                        item.setData(Qt.ItemDataRole.UserRole, group.machine)
                    self.group_table.setItem(row, col, item)
        finally:
            self.group_table.setUpdatesEnabled(True)
            self.group_table.blockSignals(False)
            self.group_table.setSortingEnabled(sorting)

    def _populate_entry_table(self, table: QTableWidget, entries: list[PressAuditEntry]) -> None:
        sorting = table.isSortingEnabled()
        table.setSortingEnabled(False)
        table.blockSignals(True)
        table.setUpdatesEnabled(False)
        try:
            table.setRowCount(len(entries))
            for row, entry in enumerate(entries):
                values = [
                    entry.audit_id,
                    entry.entry_type,
                    entry.tool,
                    entry.eoat_type,
                    entry.status,
                    entry.source_audit_id,
                    entry.known_issues,
                ]
                for col, value in enumerate(values):
                    item = QTableWidgetItem(str(value or ""))
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    table.setItem(row, col, item)
        finally:
            table.setUpdatesEnabled(True)
            table.blockSignals(False)
            table.setSortingEnabled(sorting)
        if entries:
            table.selectRow(0)

    def auto_size_columns(self) -> None:
        for table in [self.group_table, self.physical_table, self.compatible_table, self.linked_compatible_table]:
            table.resizeColumnsToContents()
        self.result_panel.show_text("Columns auto-sized.")

    def _apply_default_table_widths(self, table: QTableWidget) -> None:
        for column in range(table.columnCount()):
            table.setColumnWidth(column, 130)
        if table.columnCount():
            table.setColumnWidth(0, 170)

    def _entry_selection_changed(self, active_table: QTableWidget) -> None:
        if active_table.currentRow() >= 0:
            for table in [self.physical_table, self.compatible_table, self.linked_compatible_table]:
                if table is not active_table:
                    table.clearSelection()

    def _refresh_cards(self) -> None:
        physical = sum(len(group.physical_audits) for group in self.groups)
        compatible = sum(len(group.compatible_entries) for group in self.groups)
        linked_compatible = sum(len(group.linked_compatible_entries) for group in self.groups)
        open_items = sum(group.open_item_count for group in self.groups)
        validation = sum(group.validation_warning_count for group in self.groups)
        photos = sum(group.photo_count for group in self.groups)
        compliance_scores = [group.average_compliance_score for group in self.groups if group.average_compliance_score]
        values = {
            "Press Groups": len(self.groups),
            "Physical Audits": physical,
            "Compatible Assigned Here": compatible,
            "Links From Source": linked_compatible,
            "Open Items": open_items,
            "Validation Warnings": validation,
            "Indexed Photos": photos,
            "Avg Compliance": round(sum(compliance_scores) / len(compliance_scores)) if compliance_scores else 0,
        }
        for key, value in values.items():
            self.cards[key].set_value(str(value))

    @staticmethod
    def _matches_group_query(group: PressViewGroup, query: str) -> bool:
        needle = query.casefold().strip()
        if group.search_blob:
            return needle in group.search_blob
        haystack = " ".join(
            [
                group.machine,
                group.display_name,
                " ".join(group.tools),
                group.pilot_candidacy,
                " ".join(
                    entry.audit_id + " " + entry.status + " " + entry.eoat_type + " " + entry.known_issues
                    for entry in PressViewPage._filter_entries(group)
                ),
            ]
        ).casefold()
        return needle in haystack

    @staticmethod
    def _filter_entries(group: PressViewGroup) -> list[PressAuditEntry]:
        return [*group.physical_audits, *group.compatible_entries, *group.linked_compatible_entries]


def _time_label(value: str | None) -> str:
    if not value:
        return "last cache"
    try:
        from datetime import datetime

        return datetime.fromisoformat(str(value)).strftime("%I:%M %p").lstrip("0")
    except ValueError:
        return str(value)


def _count_phrase(count: int, singular: str, plural: str) -> str:
    return f"{count} {singular if count == 1 else plural}"
