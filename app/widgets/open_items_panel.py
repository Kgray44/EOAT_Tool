from __future__ import annotations

try:
    from PySide6.QtWidgets import QGridLayout, QLabel, QPushButton, QVBoxLayout, QWidget
except ImportError:  # pragma: no cover
    QGridLayout = QLabel = QPushButton = QVBoxLayout = QWidget = None

from core.annotations.service import AnnotationService


class OpenItemsPanel(QWidget):
    LABELS = {
        "critical_notes": ("Critical Notes", "notes"),
        "important_notes": ("Important Notes", "notes"),
        "fields_needing_review": ("Fields Needing Review", "tags"),
        "data_conflicts": ("Data Conflicts", "tags"),
        "missing_evidence": ("Missing Evidence", "tags"),
        "compatibility_concerns": ("Compatibility Concerns", "tags"),
        "documentation_gaps": ("Documentation Gaps", "tags"),
        "followups_due_soon": ("Follow-Ups Due Soon", "notes"),
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
            summary = AnnotationService(self.config.project_root).get_open_items_summary()
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
