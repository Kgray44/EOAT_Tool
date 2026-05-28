from __future__ import annotations

try:
    from PySide6.QtWidgets import QGridLayout, QLabel, QPushButton, QVBoxLayout, QWidget
except ImportError:  # pragma: no cover
    QGridLayout = QLabel = QPushButton = QVBoxLayout = QWidget = None

from core.open_items import open_items_summary


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
        self.buttons: dict[str, QPushButton] = {}
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
        self.refresh()

    def refresh(self) -> None:
        try:
            summary = open_items_summary(self.config.project_root)
        except Exception as exc:
            summary = {}
            for button in self.buttons.values():
                button.setToolTip(f"Open items unavailable: {exc}")
        for key, button in self.buttons.items():
            label, _page_key = self.LABELS[key]
            button.setText(f"{label}: {summary.get(key, 0)}")

    def _navigate(self, page_key: str) -> None:
        if self.navigate_callback is not None:
            self.navigate_callback(page_key)
