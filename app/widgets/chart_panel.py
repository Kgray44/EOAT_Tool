from __future__ import annotations

try:
    from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget
except ImportError:  # pragma: no cover
    QLabel = QVBoxLayout = QWidget = None


class ChartPanel(QWidget):
    def __init__(self, title: str = "Charts planned for later phase", parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        label = QLabel(title)
        label.setWordWrap(True)
        layout.addWidget(label)
