from __future__ import annotations

try:
    from PySide6.QtWidgets import QFileDialog
except ImportError:  # pragma: no cover
    QFileDialog = None


def select_directory(parent, caption: str, start_path: str) -> str:
    return QFileDialog.getExistingDirectory(parent, caption, start_path)


def select_file(parent, caption: str, start_path: str) -> str:
    path, _ = QFileDialog.getOpenFileName(parent, caption, start_path)
    return path

