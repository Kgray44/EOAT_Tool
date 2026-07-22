from __future__ import annotations

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QLineEdit, QVBoxLayout, QWidget


class TypedConfirmationDialog(QDialog):
    def __init__(self, title: str, explanation: str, confirmation: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.confirmation = confirmation
        layout = QVBoxLayout(self)
        detail = QLabel(explanation + f"\n\nType exactly: <b>{confirmation}</b>")
        detail.setWordWrap(True)
        layout.addWidget(detail)
        self.entry = QLineEdit()
        self.entry.setPlaceholderText(confirmation)
        layout.addWidget(self.entry)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok)
        self.accept_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.accept_button.setText(title)
        self.accept_button.setEnabled(False)
        layout.addWidget(self.buttons)
        self.entry.textChanged.connect(lambda value: self.accept_button.setEnabled(value == confirmation))
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.entry.setFocus()
