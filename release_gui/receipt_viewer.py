from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)


class ReceiptViewer(QDialog):
    def __init__(self, payload: dict[str, Any], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("EOAT Atlas Receipt Viewer")
        self.resize(850, 620)
        self.payload = payload
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        layout.addWidget(tabs)
        groups = {
            "Summary": ["mode", "final_status", "overall_readiness", "state", "receipt_path"],
            "Warnings": ["warnings"],
            "Blocking failures": ["blocking_failures"],
            "Artifact": ["artifact", "manifest"],
            "Server": ["server_inspection", "server", "health"],
            "Migration": ["migration_requirement", "migration_preflight"],
            "Deployment plan": ["future_deployment_plan"],
        }
        for title, keys in groups.items():
            subset = {key: payload[key] for key in keys if key in payload}
            if subset:
                tabs.addTab(self._text(subset), title)
        tabs.addTab(self._text(payload), "Raw JSON")
        actions = QHBoxLayout()
        copy_summary = QPushButton("Copy summary")
        copy_raw = QPushButton("Copy raw JSON")
        open_folder = QPushButton("Open receipt folder")
        save_summary = QPushButton("Save formatted summary")
        for button in (copy_summary, copy_raw, open_folder, save_summary):
            actions.addWidget(button)
        layout.addLayout(actions)
        copy_summary.clicked.connect(self.copy_summary)
        copy_raw.clicked.connect(
            lambda: self._clipboard(json.dumps(self.payload, indent=2, sort_keys=True, default=str))
        )
        open_folder.clicked.connect(self.open_receipt_folder)
        save_summary.clicked.connect(self.save_summary)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @staticmethod
    def _text(payload: object) -> QPlainTextEdit:
        text = QPlainTextEdit(json.dumps(payload, indent=2, sort_keys=True, default=str))
        text.setReadOnly(True)
        return text

    def open_receipt_folder(self) -> None:
        path = self.payload.get("receipt_path")
        if path:
            os.startfile(str(Path(path).parent))  # noqa: S606

    def copy_summary(self) -> None:
        fields = ("mode", "final_status", "overall_readiness", "state", "receipt_path")
        text = "\n".join(f"{field}: {self.payload.get(field, '—')}" for field in fields if field in self.payload)
        self._clipboard(text)

    def _clipboard(self, text: str) -> None:
        if self.clipboard():
            self.clipboard().setText(text)

    def save_summary(self) -> None:
        filename, _ = QFileDialog.getSaveFileName(
            self, "Save formatted receipt summary", "receipt-summary.txt", "Text files (*.txt)"
        )
        if filename:
            Path(filename).write_text(
                json.dumps(self.payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
            )
