from __future__ import annotations

import time

try:
    from PySide6.QtWidgets import (
        QAbstractItemView,
        QGridLayout,
        QHBoxLayout,
        QLabel,
        QPushButton,
        QTableWidget,
        QTableWidgetItem,
        QVBoxLayout,
        QWidget,
    )
except ImportError:  # pragma: no cover
    QAbstractItemView = QGridLayout = QHBoxLayout = QLabel = QPushButton = QTableWidget = QTableWidgetItem = QVBoxLayout = QWidget = None

from app.page_async import AsyncRefreshMixin, log_page_performance
from app.widgets.status_card import StatusCard
from app.widgets.tool_run_panel import ToolRunPanel
from core.openers import open_path
from core.paths import resolve_project_paths
from core.performance import read_recent_performance_events, summarize_performance


class PerformancePage(AsyncRefreshMixin, QWidget):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self._init_async_refresh("performance")
        self.cards: dict[str, StatusCard] = {}

        layout = QVBoxLayout(self)
        heading = QLabel("Performance")
        heading.setStyleSheet("font-size: 18pt; font-weight: 600;")
        layout.addWidget(heading)

        actions = QHBoxLayout()
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(lambda: self.refresh(force=True))
        open_logs = QPushButton("Open Logs Folder")
        open_logs.clicked.connect(self.open_logs_folder)
        actions.addWidget(self.refresh_button)
        actions.addWidget(open_logs)
        actions.addStretch(1)
        layout.addLayout(actions)

        grid = QGridLayout()
        for index, key in enumerate(
            [
                "Events Logged",
                "Cache Hits",
                "Cache Stale",
                "Cache Misses",
                "Warnings",
                "Errors",
                "Latest Startup",
                "Quick Refresh",
                "Deep Refresh",
                "Audit Save",
                "Validation",
                "Report Generation",
            ]
        ):
            card = StatusCard(key)
            self.cards[key] = card
            grid.addWidget(card, index // 5, index % 5)
        layout.addLayout(grid)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Operation", "Duration", "Source", "Page/Tool", "Warnings", "Errors"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table, stretch=2)

        self.result_panel = ToolRunPanel()
        self.result_panel.setMaximumHeight(220)
        layout.addWidget(self.result_panel)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.on_show()

    def refresh(self, *_args, force: bool = False) -> bool:
        return self._begin_background_refresh(
            task_id="performance_page_refresh",
            name="Performance Page Refresh",
            load=lambda: read_recent_performance_events(self.config.project_root, limit=300),
            apply_result=self._apply_refresh_result,
            button=self.refresh_button,
            force=force,
            loading_text="Reading recent performance events in background...",
        )

    def refresh_data(self) -> None:
        self.refresh()

    def on_show(self) -> None:
        self.refresh()
        return True

    def _apply_refresh_result(self, payload: tuple, data_load_seconds: float) -> None:
        render_started = time.perf_counter()
        events, warning = payload
        summary = summarize_performance(events)
        self.cards["Events Logged"].set_value(str(summary["event_count"]))
        self.cards["Cache Hits"].set_value(str(summary["cache"]["hit"]))
        self.cards["Cache Stale"].set_value(str(summary["cache"]["stale"]))
        self.cards["Cache Misses"].set_value(str(summary["cache"]["miss"]))
        self.cards["Warnings"].set_value(str(summary["warning_count"]))
        self.cards["Errors"].set_value(str(summary["error_count"]))
        self.cards["Latest Startup"].set_value(_event_duration(summary["latest"]["startup"]))
        self.cards["Quick Refresh"].set_value(_event_duration(summary["latest"]["dashboard_quick_refresh"]))
        self.cards["Deep Refresh"].set_value(_event_duration(summary["latest"]["dashboard_deep_refresh"]))
        self.cards["Audit Save"].set_value(_event_duration(summary["latest"]["audit_save"]))
        self.cards["Validation"].set_value(_event_duration(summary["latest"]["validation"]))
        self.cards["Report Generation"].set_value(_event_duration(summary["latest"]["report_generation"]))

        slowest = summary["slowest_operations"]
        self._populate_events_table(slowest)

        lines = ["Recent structured performance events are stored locally in 00_Project_Admin/logs/performance.jsonl."]
        if warning:
            lines.append(warning)
        if not events:
            lines.append("No performance events logged yet. Run a dashboard refresh or tool action to populate diagnostics.")
        else:
            lines.append(f"Slowest displayed operation: {slowest[0].get('operation', '') if slowest else 'n/a'}.")
        lines.append(f"Loaded {len(events)} performance event(s) in {data_load_seconds:.1f}s.")
        self.result_panel.show_text("\n".join(lines))
        log_page_performance(
            self.config.project_root,
            "performance",
            "data_load",
            data_load_seconds,
            details={"row_count": len(events), "source_counts": {"events": len(events)}},
        )
        log_page_performance(
            self.config.project_root,
            "performance",
            "table_render",
            time.perf_counter() - render_started,
            details={"row_count": len(slowest)},
        )

    def _populate_events_table(self, slowest: list[dict]) -> None:
        sorting = self.table.isSortingEnabled()
        self.table.setSortingEnabled(False)
        self.table.blockSignals(True)
        self.table.setUpdatesEnabled(False)
        try:
            self.table.setRowCount(len(slowest))
            for row, event in enumerate(slowest):
                values = [
                    event.get("operation", ""),
                    _event_duration(event),
                    event.get("source", ""),
                    event.get("page_tool", ""),
                    str(event.get("warning_count") or 0),
                    str(event.get("error_count") or 0),
                ]
                for column, value in enumerate(values):
                    self.table.setItem(row, column, QTableWidgetItem(str(value)))
            self.table.resizeColumnsToContents()
        finally:
            self.table.setUpdatesEnabled(True)
            self.table.blockSignals(False)
            self.table.setSortingEnabled(sorting)

    def open_logs_folder(self) -> None:
        result = open_path(resolve_project_paths(self.config.project_root).logs)
        if not result.success:
            self.result_panel.show_result(result)


def _event_duration(event: dict | None) -> str:
    if not event:
        return "n/a"
    try:
        return f"{float(event.get('duration_seconds') or 0):.2f}s"
    except (TypeError, ValueError):
        return "n/a"
