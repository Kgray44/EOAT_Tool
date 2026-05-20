from __future__ import annotations

try:
    from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout
except ImportError:  # pragma: no cover
    QFrame = QLabel = QPushButton = QVBoxLayout = None


class WorkflowCard(QFrame):
    def __init__(self, title: str, description: str, actions: list[tuple[str, object]], parent=None):
        super().__init__(parent)
        self.setObjectName("WorkflowCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(7)
        title_label = QLabel(title)
        title_label.setObjectName("WorkflowCardTitle")
        description_label = QLabel(description)
        description_label.setObjectName("WorkflowCardDescription")
        description_label.setWordWrap(True)
        layout.addWidget(title_label)
        layout.addWidget(description_label)
        for label, callback in actions:
            button = QPushButton(label)
            button.setObjectName("WorkflowActionButton")
            button.clicked.connect(callback)
            layout.addWidget(button)
        layout.addStretch(1)
