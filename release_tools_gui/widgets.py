"""Small accessible widgets shared by both Phase 1 pages."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QSplitter,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .models import OperationResult
from .receipts import ReceiptStore
from .redaction import sanitize


class StatusBanner(QLabel):
    def set_result(self, result: OperationResult | None) -> None:
        if result is None:
            self.setText("NOT RUN — no operation has completed")
            self.setAccessibleName("Operation status: not run")
            return
        self.setText(f"{result.status.value} — {result.summary}")
        self.setAccessibleName(f"Operation status: {result.status.value}; {result.summary}")
        self.setProperty("status", result.status.value)
        self.style().unpolish(self)
        self.style().polish(self)


def _tree_item(parent: QTreeWidgetItem, key: str, value: Any) -> None:
    if isinstance(value, dict):
        item = QTreeWidgetItem([key, ""])
        parent.addChild(item)
        for child_key, child_value in value.items():
            _tree_item(item, str(child_key), child_value)
    elif isinstance(value, list):
        item = QTreeWidgetItem([key, f"{len(value)} item(s)"])
        parent.addChild(item)
        for index, child in enumerate(value):
            _tree_item(item, f"[{index}]", child)
    else:
        parent.addChild(QTreeWidgetItem([key, str(value)]))


class DetailTree(QTreeWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setHeaderLabels(["Field", "Sanitized value"])
        self.setAccessibleName("Expandable structured validation details")
        self.setAlternatingRowColors(True)

    def set_result(self, result: OperationResult | None) -> None:
        self.clear()
        if result is None:
            return
        root = QTreeWidgetItem([result.operation, result.status.value])
        self.addTopLevelItem(root)
        payload = {"blockers": list(result.blockers), "warnings": list(result.warnings), **sanitize(result.details)}
        for key, value in payload.items():
            _tree_item(root, key, value)
        self.expandToDepth(1)
        self.resizeColumnToContents(0)


class ReceiptBrowser(QWidget):
    selected = Signal(object)

    def __init__(self, store: ReceiptStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.store = store
        self.paths: list[Path] = []
        self.listing = QListWidget()
        self.listing.setAccessibleName("Sanitized receipt history")
        self.preview = QTextEdit(readOnly=True)
        self.preview.setAccessibleName("Sanitized receipt preview")
        refresh = QPushButton("Refresh receipts")
        open_folder = QPushButton("Open receipt folder")
        copy = QPushButton("Copy sanitized summary")
        refresh.clicked.connect(self.refresh)
        open_folder.clicked.connect(self.open_folder)
        copy.clicked.connect(self.copy_summary)
        self.listing.currentRowChanged.connect(self._select)
        actions = QHBoxLayout()
        actions.addWidget(refresh)
        actions.addWidget(open_folder)
        actions.addWidget(copy)
        split = QSplitter(Qt.Orientation.Vertical)
        split.addWidget(self.listing)
        split.addWidget(self.preview)
        layout = QVBoxLayout(self)
        layout.addLayout(actions)
        layout.addWidget(split)

    def refresh(self) -> None:
        self.paths = self.store.list()
        self.listing.clear()
        self.listing.addItems([path.name for path in self.paths])
        if self.paths:
            self.listing.setCurrentRow(0)
        else:
            self.preview.setPlainText("No sanitized GUI receipts have been saved yet.")

    def _select(self, row: int) -> None:
        if row < 0 or row >= len(self.paths):
            return
        payload = self.store.load(self.paths[row])
        self.preview.setPlainText(json.dumps(payload, indent=2, sort_keys=True))
        self.selected.emit(payload)

    def open_folder(self) -> None:
        self.store.directory.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.store.directory)))

    def copy_summary(self) -> None:
        try:
            payload = json.loads(self.preview.toPlainText())
        except json.JSONDecodeError:
            payload = {"summary": self.preview.toPlainText()}
        summary = {
            key: payload.get(key)
            for key in (
                "tool",
                "operation",
                "status",
                "summary",
                "blockers",
                "warnings",
                "started_at_utc",
                "ended_at_utc",
            )
        }
        QGuiApplication.clipboard().setText(json.dumps(summary, indent=2, sort_keys=True))
