from __future__ import annotations

import time
from collections import Counter

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import (
        QComboBox,
        QFormLayout,
        QGridLayout,
        QGroupBox,
        QHBoxLayout,
        QInputDialog,
        QLabel,
        QLineEdit,
        QMessageBox,
        QPushButton,
        QTableWidget,
        QTableWidgetItem,
        QTextEdit,
        QVBoxLayout,
        QWidget,
    )
except ImportError:  # pragma: no cover
    Qt = None
    QComboBox = QFormLayout = QGridLayout = QGroupBox = QHBoxLayout = QInputDialog = QLabel = QLineEdit = (
        QMessageBox
    ) = QPushButton = QTableWidget = QTableWidgetItem = QTextEdit = QVBoxLayout = QWidget = None

from app.event_bus import EVENT_AUDIT_SAVED, EVENT_OPEN_ITEMS_CHANGED, get_event_bus
from app.page_async import AsyncRefreshMixin, log_page_performance
from app.widgets.annotation_target_navigator import AnnotationTargetNavigator
from core.action_items import add_action_item
from core.annotations.service import AnnotationService
from core.open_items import (
    OPEN_ITEM_STATUSES,
    OpenItem,
    dismiss_open_item,
    export_open_items_report,
    list_open_items,
    load_cached_open_items,
    summarize_open_items,
)


class OpenItemsPage(AsyncRefreshMixin, QWidget):
    COLUMNS = [
        "Source",
        "Severity",
        "Category",
        "Status",
        "Title",
        "Audit ID",
        "Machine",
        "Field",
        "Due Date",
        "Recommended Action",
    ]

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self._init_async_refresh("open_items")
        self.items: list[OpenItem] = []
        self.filtered_items: list[OpenItem] = []
        self._latest_generated_at = ""

        layout = QVBoxLayout(self)
        heading = QLabel("Open Items")
        heading.setStyleSheet("font-size: 18pt; font-weight: 600;")
        layout.addWidget(heading)

        self.summary_group = QGroupBox("Summary")
        self.summary_grid = QGridLayout(self.summary_group)
        self.summary_labels: dict[str, QLabel] = {}
        for index, label in enumerate(
            [
                "Total Open",
                "Critical",
                "Overdue",
                "Missing Evidence",
                "Data Conflicts",
                "Dismissed / Overridden",
                "Fixed at Source This Week",
            ]
        ):
            title = QLabel(label)
            value = QLabel("0")
            value.setStyleSheet("font-size: 16pt; font-weight: 700;")
            self.summary_grid.addWidget(title, 0, index)
            self.summary_grid.addWidget(value, 1, index)
            self.summary_labels[label] = value
        layout.addWidget(self.summary_group)

        filter_group = QGroupBox("Filters")
        filter_layout = QGridLayout(filter_group)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search title, message, audit ID, machine, field, tag, or action...")
        self.search_edit.textChanged.connect(self.apply_filters)
        self.source_filter = self._combo(["All"])
        self.severity_filter = self._combo(["All", "Critical", "Error", "Warning", "Info"])
        self.category_filter = self._combo(["All"])
        self.status_filter = self._combo(
            ["Open", "All", *[status for status in OPEN_ITEM_STATUSES if status != "Open"]]
        )
        self.tag_filter = self._combo(["All"])
        self.audit_filter = QLineEdit()
        self.audit_filter.setPlaceholderText("Audit ID")
        self.audit_filter.textChanged.connect(self.apply_filters)
        self.machine_filter = QLineEdit()
        self.machine_filter.setPlaceholderText("Machine")
        self.machine_filter.textChanged.connect(self.apply_filters)
        self.due_filter = self._combo(["All", "Overdue", "Due Soon", "No Due Date"])
        filters = [
            ("Search", self.search_edit),
            ("Source", self.source_filter),
            ("Severity", self.severity_filter),
            ("Category", self.category_filter),
            ("Status", self.status_filter),
            ("Tag", self.tag_filter),
            ("Audit", self.audit_filter),
            ("Machine", self.machine_filter),
            ("Due", self.due_filter),
        ]
        for index, (label, widget) in enumerate(filters):
            filter_layout.addWidget(QLabel(label), index // 3 * 2, index % 3)
            filter_layout.addWidget(widget, index // 3 * 2 + 1, index % 3)
        layout.addWidget(filter_group)

        self.table = QTableWidget()
        self.table.setColumnCount(len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.itemSelectionChanged.connect(self._update_detail)
        layout.addWidget(self.table, stretch=1)

        detail_group = QGroupBox("Selected Item")
        detail_layout = QVBoxLayout(detail_group)
        self.detail_text = QTextEdit()
        self.detail_text.setReadOnly(True)
        self.detail_text.setMaximumHeight(110)
        detail_layout.addWidget(self.detail_text)
        layout.addWidget(detail_group)

        action_row = QHBoxLayout()
        open_button = QPushButton("Open Target")
        open_button.clicked.connect(self.open_target)
        fix_button = QPushButton("Fix at Source")
        fix_button.clicked.connect(self.fix_at_source)
        dismiss_button = QPushButton("Dismiss With Reason")
        dismiss_button.clicked.connect(self.dismiss_selected)
        note_button = QPushButton("Add Note")
        note_button.clicked.connect(self.add_note)
        followup_button = QPushButton("Create Follow-Up")
        followup_button.clicked.connect(self.create_follow_up)
        export_button = QPushButton("Export Open Items Report")
        export_button.clicked.connect(self.export_report)
        self.refresh_button = QPushButton("Quick Refresh")
        self.refresh_button.clicked.connect(lambda: self.refresh(force=True))
        self.deep_rebuild_button = QPushButton("Deep Rebuild Open Items")
        self.deep_rebuild_button.clicked.connect(lambda: self.deep_rebuild(force=True))
        for button in [
            open_button,
            fix_button,
            dismiss_button,
            note_button,
            followup_button,
            export_button,
            self.refresh_button,
            self.deep_rebuild_button,
        ]:
            action_row.addWidget(button)
        action_row.addStretch(1)
        layout.addLayout(action_row)

        self.status_label = QLabel()
        self.status_label.setObjectName("MutedText")
        layout.addWidget(self.status_label)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.on_show()

    def _combo(self, values: list[str]) -> QComboBox:
        combo = QComboBox()
        combo.addItems(values)
        combo.currentTextChanged.connect(self.apply_filters)
        return combo

    def refresh(self, *_args, force: bool = False) -> bool:
        def _load() -> dict:
            items, generated_at, warning = load_cached_open_items(self.config.project_root, include_resolved=True)
            try:
                tags = [tag.name for tag in AnnotationService(self.config.project_root).list_tags()]
            except Exception:
                tags = []
            return {
                "items": items,
                "tags": tags,
                "summary": summarize_open_items(items),
                "source_counts": dict(Counter(item.source for item in items)),
                "generated_at": generated_at,
                "warning": warning,
                "cached": True,
            }

        return self._begin_background_refresh(
            task_id="open_items_refresh",
            name="Open Items Quick Refresh",
            load=_load,
            apply_result=self._apply_refresh_result,
            button=self.refresh_button,
            force=force,
            loading_text="Loading cached open items...",
        )

    def deep_rebuild(self, *_args, force: bool = False) -> bool:
        def _load() -> dict:
            items = list_open_items(self.config.project_root, include_resolved=True, include_validation=True)
            try:
                tags = [tag.name for tag in AnnotationService(self.config.project_root).list_tags()]
            except Exception:
                tags = []
            return {
                "items": items,
                "tags": tags,
                "summary": summarize_open_items(items),
                "source_counts": dict(Counter(item.source for item in items)),
                "cached": False,
            }

        return self._begin_background_refresh(
            task_id="open_items_deep_rebuild",
            name="Deep Rebuild Open Items",
            load=_load,
            apply_result=self._apply_refresh_result,
            button=self.deep_rebuild_button,
            force=force,
            loading_text="Deep rebuild running in background: notes, tags, action items, evidence, documentation, validation...",
        )

    def refresh_data(self) -> None:
        self.refresh()

    def on_show(self) -> None:
        started = time.perf_counter()
        self._show_cached_items()
        log_page_performance(
            self.config.project_root,
            "open_items",
            "cached_show",
            time.perf_counter() - started,
            details={"row_count": len(self.items), "cached_only": True},
        )
        return True

    def on_event(self, event) -> None:
        if getattr(event, "event_type", "") == EVENT_AUDIT_SAVED:
            self.status_label.setText(
                "Audit saved. Open Items are marked stale; use Deep Rebuild Open Items when you need a full source rebuild."
            )
            return True
        self.status_label.setText(
            "Open Items cache may be stale; use Quick Refresh for cached data or Deep Rebuild Open Items for source validation."
        )
        return True

    def on_project_root_changed(self, config) -> None:
        self.config = config
        self.items = []
        self.filtered_items = []
        self._populate_table([])
        self._show_cached_items()

    def apply_filters(self, *_args) -> None:
        needle = self.search_edit.text().casefold().strip()
        source = self.source_filter.currentText()
        severity = self.severity_filter.currentText()
        category = self.category_filter.currentText()
        status = self.status_filter.currentText()
        tag = self.tag_filter.currentText()
        audit = self.audit_filter.text().casefold().strip()
        machine = self.machine_filter.text().casefold().strip()
        due = self.due_filter.currentText()

        rows: list[OpenItem] = []
        for item in self.items:
            haystack = " ".join(
                [
                    item.source,
                    item.severity,
                    item.category,
                    item.status,
                    item.title,
                    item.message,
                    item.audit_id,
                    item.machine,
                    item.field,
                    item.recommended_action,
                ]
            ).casefold()
            if needle and needle not in haystack:
                continue
            if source != "All" and item.source != source:
                continue
            if severity != "All" and item.severity != severity:
                continue
            if category != "All" and item.category != category:
                continue
            if status != "All" and item.status != status:
                continue
            if tag != "All" and tag.casefold() not in haystack:
                continue
            if audit and audit not in item.audit_id.casefold():
                continue
            if machine and machine not in item.machine.casefold():
                continue
            if due != "All" and not self._matches_due_filter(item, due):
                continue
            rows.append(item)
        self.filtered_items = rows
        self._populate_table(rows)
        self.status_label.setText(f"{len(rows)} item(s) shown from {len(self.items)} total item(s).")

    def selected_item(self) -> OpenItem | None:
        row = self.table.currentRow()
        if 0 <= row < len(self.filtered_items):
            return self.filtered_items[row]
        return None

    def open_target(self) -> None:
        item = self.selected_item()
        if item is None:
            self.status_label.setText("Select an open item first.")
            return
        target = item.target_payload()
        if not target:
            self.status_label.setText(
                f"Selected item does not have a direct target. Fix manually: {item.recommended_action}"
            )
            return
        if not AnnotationTargetNavigator(self).open_target(target):
            self.status_label.setText(f"Could not open a direct target. Fix manually: {item.recommended_action}")

    def mark_resolved(self) -> None:
        self.status_label.setText(
            "Generated open items cannot be manually marked resolved. Use Fix at Source or Dismiss With Reason."
        )

    def fix_at_source(self) -> None:
        item = self.selected_item()
        if item is None:
            self.status_label.setText("Select an item to fix at source.")
            return
        target = item.source_payload()
        if not target:
            self.status_label.setText(f"Fix manually: {item.recommended_action}")
            return
        if AnnotationTargetNavigator(self).open_target(target):
            self.status_label.setText(
                "Opened the source target. Refresh Open Items after correcting the underlying source data."
            )
        else:
            self.status_label.setText(f"Could not open the source target. Fix manually: {item.recommended_action}")

    def dismiss_selected(self) -> None:
        item = self.selected_item()
        if item is None:
            self.status_label.setText("Select an item to dismiss.")
            return
        reason, ok = QInputDialog.getText(self, "Dismiss Open Item", "Reason:")
        if not ok:
            return
        reason_text = reason.strip()
        if not reason_text:
            self.status_label.setText("Dismissal reason is required.")
            return
        try:
            dismiss_open_item(self.config.project_root, item.id, reason=reason_text)
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        get_event_bus().emit(
            EVENT_OPEN_ITEMS_CHANGED, {"item_id": item.id, "status": "Dismissed / Overridden"}, source="open_items"
        )
        self.refresh(force=True)

    def add_note(self) -> None:
        item = self.selected_item()
        if item is None:
            self.status_label.setText("Select an item before adding a note.")
            return
        service = AnnotationService(self.config.project_root)
        target_ids = []
        target = item.target_payload()
        if target:
            if target.get("id"):
                target_ids.append(str(target["id"]))
            else:
                target_ids.append(service.create_or_get_target(**target).id)
        note = service.create_note(
            f"Open item: {item.title}",
            f"{item.message}\n\nRecommended action: {item.recommended_action}",
            "Important" if item.severity in {"Critical", "Error", "Warning"} else "Neutral",
            status="Open",
            target_ids=target_ids,
        )
        get_event_bus().emit(EVENT_OPEN_ITEMS_CHANGED, {"item_id": item.id, "note_id": note.id}, source="open_items")
        self.status_label.setText(f"Added note: {note.subject}")
        self.refresh(force=True)

    def create_follow_up(self) -> None:
        item = self.selected_item()
        if item is None:
            self.status_label.setText("Select an item before creating a follow-up.")
            return
        result = add_action_item(
            self.config.project_root,
            f"Follow up on open item: {item.title}",
            related_cell_press=item.machine,
            priority="High" if item.severity in {"Critical", "Error"} else "Medium",
            notes=f"{item.message}\nRecommended action: {item.recommended_action}",
        )
        if result.success:
            get_event_bus().emit(
                EVENT_OPEN_ITEMS_CHANGED, {"item_id": item.id, "followup_created": True}, source="open_items"
            )
            self.refresh(force=True)
        message = result.summary if result.success else "; ".join(result.errors)
        self.status_label.setText(message)

    def export_report(self) -> None:
        path = export_open_items_report(self.config.project_root, self.filtered_items)
        self.status_label.setText(f"Exported Open Items report: {path}")

    def _show_cached_items(self) -> None:
        cached, generated_at, warning = load_cached_open_items(self.config.project_root, include_resolved=True)
        if not cached:
            self.status_label.setText(
                f"{warning or 'No cached open items yet.'} Use Deep Rebuild Open Items to build it."
            )
            return
        self.items = cached
        self._latest_generated_at = generated_at or ""
        self._refresh_filter_options([])
        self._refresh_summary(summarize_open_items(cached))
        self.apply_filters()
        self.status_label.setText(f"Showing cached data from {_time_label(generated_at)}.")

    def _loading_text(self) -> str:
        if self.items:
            return f"Showing cached data from {_time_label(self._latest_generated_at)}."
        return "Loading cached open items..."

    def _apply_refresh_result(self, payload: dict, data_load_seconds: float) -> None:
        render_started = time.perf_counter()
        self.items = list(payload.get("items") or [])
        self._refresh_filter_options(list(payload.get("tags") or []))
        self._refresh_summary(dict(payload.get("summary") or summarize_open_items(self.items)))
        self.apply_filters()
        render_seconds = time.perf_counter() - render_started
        source_counts = dict(payload.get("source_counts") or {})
        log_page_performance(
            self.config.project_root,
            "open_items",
            "data_load",
            data_load_seconds,
            details={"row_count": len(self.items), "source_counts": source_counts},
        )
        log_page_performance(
            self.config.project_root,
            "open_items",
            "table_render",
            render_seconds,
            details={"row_count": len(self.filtered_items), "source_counts": source_counts},
        )
        from core.performance import log_performance_event

        log_performance_event(
            self.config.project_root,
            "open_items.rebuild.table_render",
            render_seconds,
            source="open_items",
            page_tool="open_items",
            details={"row_count": len(self.filtered_items), "cached": bool(payload.get("cached"))},
        )
        if payload.get("cached"):
            self._latest_generated_at = str(payload.get("generated_at") or self._latest_generated_at)
            warning = str(payload.get("warning") or "")
            self.status_label.setText(
                warning or f"Loaded {len(self.filtered_items)} cached open item(s) in {data_load_seconds:.1f}s."
            )
        else:
            self.status_label.setText(
                f"Deep rebuild loaded {len(self.filtered_items)} open items in {data_load_seconds:.1f}s."
            )

    def _refresh_filter_options(self, tags: list[str]) -> None:
        self._set_combo_values(self.source_filter, ["All", *sorted({item.source for item in self.items})])
        self._set_combo_values(self.category_filter, ["All", *sorted({item.category for item in self.items})])
        self._set_combo_values(self.tag_filter, ["All", *tags])

    def _set_combo_values(self, combo: QComboBox, values: list[str]) -> None:
        current = combo.currentText()
        combo.blockSignals(True)
        combo.clear()
        combo.addItems(values)
        index = combo.findText(current)
        combo.setCurrentIndex(index if index >= 0 else 0)
        combo.blockSignals(False)

    def _refresh_summary(self, summary: dict[str, int]) -> None:
        values = {
            "Total Open": summary.get("total_open_items", 0),
            "Critical": summary.get("critical_open_items", 0),
            "Overdue": summary.get("overdue_followups", 0),
            "Missing Evidence": summary.get("missing_evidence_count", 0),
            "Data Conflicts": summary.get("data_conflict_count", 0),
            "Dismissed / Overridden": summary.get("dismissed_overridden_count", 0),
            "Fixed at Source This Week": summary.get("items_fixed_at_source_this_week", 0),
        }
        for key, value in values.items():
            self.summary_labels[key].setText(str(value))

    def _populate_table(self, items: list[OpenItem]) -> None:
        sorting = self.table.isSortingEnabled()
        self.table.setSortingEnabled(False)
        self.table.blockSignals(True)
        self.table.setUpdatesEnabled(False)
        try:
            self.table.setRowCount(len(items))
            for row_index, item in enumerate(items):
                values = [
                    item.source,
                    item.severity,
                    item.category,
                    item.status,
                    item.title,
                    item.audit_id,
                    item.machine,
                    item.field,
                    item.due_date,
                    item.recommended_action,
                ]
                for col, value in enumerate(values):
                    table_item = QTableWidgetItem(str(value or ""))
                    if col == 0:
                        table_item.setData(Qt.ItemDataRole.UserRole, item.id)
                    if col in {4, 9}:
                        table_item.setToolTip(str(value or ""))
                    self.table.setItem(row_index, col, table_item)
            self.table.resizeColumnsToContents()
        finally:
            self.table.setUpdatesEnabled(True)
            self.table.blockSignals(False)
            self.table.setSortingEnabled(sorting)
        self._update_detail()

    def _update_detail(self) -> None:
        item = self.selected_item()
        if item is None:
            self.detail_text.setPlainText("")
            return
        self.detail_text.setPlainText(
            "\n".join(
                [
                    f"ID: {item.id}",
                    f"Message: {item.message}",
                    f"Recommended action: {item.recommended_action}",
                    f"Dismissal reason: {item.dismissed_reason}" if item.dismissed_reason else "",
                ]
            ).strip()
        )

    def _matches_due_filter(self, item: OpenItem, due_filter: str) -> bool:
        from datetime import date as date_type

        if due_filter == "No Due Date":
            return not item.due_date
        if not item.due_date:
            return False
        try:
            due = date_type.fromisoformat(item.due_date[:10])
        except ValueError:
            return False
        today = date_type.today()
        if due_filter == "Overdue":
            return due < today
        if due_filter == "Due Soon":
            return 0 <= (due - today).days <= 7
        return True


def _time_label(value: str | None) -> str:
    if not value:
        return "last cache"
    try:
        from datetime import datetime

        return datetime.fromisoformat(str(value)).strftime("%I:%M %p").lstrip("0")
    except ValueError:
        return str(value)
