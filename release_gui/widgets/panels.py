from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QPushButton, QTextEdit, QVBoxLayout, QWidget


class StatusCard(QFrame):
    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.title, self.value, self.detail = QLabel(title), QLabel("UNKNOWN"), QLabel("")
        self.value.setStyleSheet("font-size: 20px; font-weight: 700;")
        layout = QVBoxLayout(self)
        layout.addWidget(self.title)
        layout.addWidget(self.value)
        layout.addWidget(self.detail)

    def set_status(self, status: str, detail: str = "") -> None:
        palette = (
            "#2e7d32"
            if status.startswith(("READY", "PASS", "VERIFIED", "VALID", "SUCCEEDED"))
            else "#c62828"
            if status.startswith(("FAIL", "NOT_READY", "REJECTED"))
            else "#9a6700"
        )
        self.value.setText(status.replace("_", " "))
        self.value.setStyleSheet(f"font-size: 20px; font-weight: 700; color: {palette};")
        self.detail.setText(detail)


class KeyValuePanel(QFrame):
    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"<b>{title}</b>"))
        self.grid = QGridLayout()
        layout.addLayout(self.grid)

    def set_values(self, values: dict[str, object]) -> None:
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for row, (key, value) in enumerate(values.items()):
            self.grid.addWidget(QLabel(str(key).replace("_", " ").title()), row, 0)
            label = QLabel(str(value) if value is not None else "—")
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.grid.addWidget(label, row, 1)


class WarningPanel(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.label = QLabel()
        self.label.setWordWrap(True)
        QVBoxLayout(self).addWidget(self.label)
        self.hide()

    def show_messages(self, warnings: list[str], blockers: list[str]) -> None:
        messages = [f"<b>Blocking:</b> {item}" for item in blockers] + [f"<b>Warning:</b> {item}" for item in warnings]
        self.label.setText("<br>".join(messages))
        self.setStyleSheet("background: #fff3cd; padding: 8px;")
        self.setVisible(bool(messages))


class OperationLog(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.display = QTextEdit(readOnly=True)
        self.copy_button = QPushButton("Copy visible log")
        self.clear_button = QPushButton("Clear display")
        layout = QVBoxLayout(self)
        layout.addWidget(self.display)
        layout.addWidget(self.copy_button)
        layout.addWidget(self.clear_button)
        self.copy_button.clicked.connect(lambda: self.display.copy())
        self.clear_button.clicked.connect(self.display.clear)

    def add(self, message: str) -> None:
        self.display.append(message)
