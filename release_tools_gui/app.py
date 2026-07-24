"""Shared application shell and thin launch entry point."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QMainWindow, QPushButton, QStackedWidget, QToolBar

from .pages import PackagerPage, UpdaterPage
from .receipts import ReceiptStore
from .widgets import ReceiptBrowser


class ReleaseToolsWindow(QMainWindow):
    def __init__(self, root: Path) -> None:
        super().__init__()
        self.root = root.resolve()
        self.setWindowTitle("EOAT Atlas Release Tools — Phase 1 Read-only")
        self.setMinimumSize(900, 640)
        self.resize(1200, 820)
        self.store = ReceiptStore(self.root)
        self.stack = QStackedWidget()
        self.packager = PackagerPage(self.root, self.store)
        self.updater = UpdaterPage(self.root, self.store)
        self.stack.addWidget(self.packager)
        self.stack.addWidget(self.updater)
        self.setCentralWidget(self.stack)
        toolbar = QToolBar("Navigation", self)
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        packager = QPushButton("Packager")
        updater = QPushButton("Updater")
        receipts = QPushButton("Receipts")
        appearance = QPushButton("Toggle dark appearance")
        packager.clicked.connect(lambda: self.stack.setCurrentWidget(self.packager))
        updater.clicked.connect(lambda: self.stack.setCurrentWidget(self.updater))
        receipts.clicked.connect(self.show_receipts)
        appearance.clicked.connect(self.toggle_appearance)
        for button in (packager, updater, receipts, appearance):
            toolbar.addWidget(button)
        self._settings = QSettings("EOAT Atlas", "Release Tools GUI")
        self._dark = bool(self._settings.value("dark", False, type=bool))
        self._apply_appearance()

    def show_receipts(self) -> None:
        browser = ReceiptBrowser(self.store, self)
        browser.setWindowTitle("Sanitized receipt history")
        browser.resize(760, 600)
        browser.refresh()
        browser.show()
        self._receipt_browser = browser

    def toggle_appearance(self) -> None:
        self._dark = not self._dark
        self._settings.setValue("dark", self._dark)
        self._apply_appearance()

    def _apply_appearance(self) -> None:
        self.setStyleSheet(
            "QMainWindow { background: #111827; color: #e5edf7; } QWidget { color: #e5edf7; } "
            "QLineEdit, QTreeWidget, QTextEdit, QComboBox, QListWidget { background: #1f2937; color: #f8fafc; } "
            "QPushButton { padding: 6px 10px; } QLabel[status='PASS'] { color: #42d392; } "
            "QLabel[status='WARNING'] { color: #f5b342; } QLabel[status='BLOCKED'], QLabel[status='FAILED'] { color: #ff8179; }"
            if self._dark
            else "QMainWindow { background: #eef3f8; color: #102033; } QWidget { color: #102033; } "
            "QLineEdit, QTreeWidget, QTextEdit, QComboBox, QListWidget { background: white; color: #102033; } "
            "QPushButton { padding: 6px 10px; } QLabel[status='PASS'] { color: #087f5b; } "
            "QLabel[status='WARNING'] { color: #b76a00; } QLabel[status='BLOCKED'], QLabel[status='FAILED'] { color: #b42318; }"
        )


def main(root: Path | None = None) -> int:
    application = QApplication.instance() or QApplication(sys.argv)
    window = ReleaseToolsWindow(root or Path(__file__).resolve().parents[1])
    window.show()
    return application.exec()
