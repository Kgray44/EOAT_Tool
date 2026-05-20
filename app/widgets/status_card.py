from __future__ import annotations

try:
    from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout
except ImportError:  # pragma: no cover
    QFrame = QLabel = QVBoxLayout = None


class StatusCard(QFrame):
    def __init__(self, title: str, value: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("StatusCard")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("StatusCardTitle")
        self.value_label = QLabel(value)
        self.value_label.setObjectName("StatusCardValue")
        self.value_label.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(5)
        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)

    def set_value(self, value: str) -> None:
        self.value_label.setText(value)
