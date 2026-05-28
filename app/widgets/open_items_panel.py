from __future__ import annotations

import time

try:
    from PySide6.QtWidgets import QGridLayout, QLabel, QPushButton, QVBoxLayout, QWidget
except ImportError:  # pragma: no cover
    QGridLayout = QLabel = QPushButton = QVBoxLayout = QWidget = None

from app.task_runner import TaskRequest, get_task_manager
from core import open_items as open_items_core
from core.performance import log_performance


class OpenItemsPanel(QWidget):
    LABELS = {
        "total_open_items": ("Total Open", "open_items"),
        "critical_open_items": ("Critical", "open_items"),
        "overdue_followups": ("Overdue Follow-Ups", "open_items"),
        "missing_evidence_count": ("Missing Evidence", "open_items"),
        "data_conflict_count": ("Data Conflicts", "open_items"),
        "blocked_items": ("Blocked", "open_items"),
        "dismissed_overridden_count": ("Dismissed / Overridden", "open_items"),
        "items_fixed_at_source_this_week": ("Fixed at Source This Week", "open_items"),
    }

    def __init__(self, config, navigate_callback=None, parent=None):
        super().__init__(parent)
        self.config = config
        self.navigate_callback = navigate_callback
        self._last_summary: dict[str, int] = {}
        self._refresh_running = False
        self._destroyed = False
        self.buttons: dict[str, QPushButton] = {}
        self.destroyed.connect(lambda *_args: setattr(self, "_destroyed", True))
        layout = QVBoxLayout(self)
        title = QLabel("Open Items")
        title.setStyleSheet("font-size: 12pt; font-weight: 700;")
        layout.addWidget(title)
        grid = QGridLayout()
        for index, (key, (label, page_key)) in enumerate(self.LABELS.items()):
            button = QPushButton(f"{label}: 0")
            button.setProperty("page_key", page_key)
            button.clicked.connect(lambda _checked=False, p=page_key: self._navigate(p))
            self.buttons[key] = button
            grid.addWidget(button, index // 4, index % 4)
        layout.addLayout(grid)
        self._load_cached_summary()

    def _load_cached_summary(self) -> None:
        started = time.perf_counter()
        summary, generated_at = open_items_core.load_cached_open_items_summary(self.config.project_root)
        log_performance(
            self.config.project_root,
            "open_items.cache_load",
            time.perf_counter() - started,
            source="open_items",
            page_tool="home",
            details={"cache_status": "hit" if summary is not None else "miss"},
        )
        if summary is None:
            self._apply_summary({}, tooltip="Open item counts are loading in the background.", loading=True)
            return
        label = f"Cached open item counts from {generated_at}." if generated_at else "Cached open item counts."
        self._apply_summary(summary, tooltip=label)

    def _apply_summary(self, summary: dict[str, int], *, tooltip: str = "", loading: bool = False) -> None:
        self._last_summary = dict(summary)
        for key, button in self._live_buttons():
            label, _page_key = self.LABELS[key]
            value = "Loading..." if loading and key not in summary else str(summary.get(key, 0))
            button.setText(f"{label}: {value}")
            button.setToolTip(tooltip)

    def refresh(self) -> None:
        self.refresh_async()

    def refresh_async(self) -> bool:
        if self._refresh_running:
            return False
        self._refresh_running = True
        live_buttons = self._live_buttons()
        if not live_buttons:
            self._refresh_running = False
            return False
        for _key, button in live_buttons:
            button.setToolTip("Refreshing open item counts in the background.")

        def _refresh() -> dict[str, int]:
            started = time.perf_counter()
            summary = open_items_core.open_items_summary(self.config.project_root)
            open_items_core.save_cached_open_items_summary(self.config.project_root, summary)
            log_performance(
                self.config.project_root,
                "open_items.background_refresh",
                time.perf_counter() - started,
                source="open_items",
                page_tool="home",
                details={"summary_keys": len(summary)},
            )
            return summary

        def _finished(task_result) -> None:
            self._refresh_running = False
            if not self._live_buttons():
                return
            if task_result.ok:
                self._apply_summary(task_result.result_data, tooltip="Open item counts refreshed.")
            else:
                message = task_result.error or task_result.message or "Open items refresh failed."
                for _key, button in self._live_buttons():
                    button.setToolTip(f"Open items unavailable: {message}")

        return get_task_manager().run_task(
            TaskRequest(
                id="open_items_summary_refresh",
                name="Open Items Summary Refresh",
                category="home",
                callable=_refresh,
            ),
            on_finished=_finished,
        )

    def _navigate(self, page_key: str) -> None:
        if self.navigate_callback is not None:
            self.navigate_callback(page_key)

    def _live_buttons(self) -> list[tuple[str, QPushButton]]:
        if self._destroyed:
            return []
        live: list[tuple[str, QPushButton]] = []
        for key, button in list(self.buttons.items()):
            try:
                button.text()
            except RuntimeError:
                continue
            live.append((key, button))
        return live
