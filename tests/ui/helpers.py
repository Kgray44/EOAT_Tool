from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton, QTableWidget, QWidget

from app.task_runner import get_task_manager


def process_events(ms: int = 20) -> None:
    app = QApplication.instance()
    if app is not None:
        app.processEvents()
    QTest.qWait(ms)


def wait_until(predicate: Callable[[], bool], timeout_ms: int = 10000, message: str = "condition") -> None:
    deadline = time.monotonic() + timeout_ms / 1000
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            if predicate():
                return
        except Exception as exc:  # pragma: no cover - diagnostic path
            last_error = exc
        process_events(25)
    suffix = f"; last error: {last_error}" if last_error else ""
    raise AssertionError(f"Timed out waiting for {message}{suffix}")


def wait_for_background_tasks(timeout_ms: int = 20000) -> None:
    manager = get_task_manager()

    def idle() -> bool:
        app = QApplication.instance()
        if app is not None:
            app.processEvents()
        return not manager.guard._active_ids and not manager._active_runnables

    wait_until(idle, timeout_ms=timeout_ms, message="background tasks to finish")
    process_events(50)


def wait_for_path(path: str | Path, timeout_ms: int = 10000) -> Path:
    target = Path(path)
    wait_until(target.exists, timeout_ms=timeout_ms, message=f"{target} to exist")
    return target


def find_button(widget: QWidget, text: str) -> QPushButton:
    for button in widget.findChildren(QPushButton):
        if button.text() == text or button.text().startswith(text):
            return button
    labels = sorted(button.text() for button in widget.findChildren(QPushButton))
    raise AssertionError(f"Could not find button {text!r}. Available buttons: {labels}")


def click_button(widget: QWidget, text: str) -> QPushButton:
    button = find_button(widget, text)
    assert button.isEnabled(), f"Button {button.text()!r} is disabled"
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    process_events(50)
    return button


def table_text(table: QTableWidget) -> str:
    values: list[str] = []
    for row in range(table.rowCount()):
        for col in range(table.columnCount()):
            item = table.item(row, col)
            if item is not None:
                values.append(item.text())
    return "\n".join(values)


def assert_only_fake_project_paths(project_root: Path, paths: list[str | Path]) -> None:
    root = project_root.resolve()
    for raw in paths:
        path = Path(raw)
        if not path.is_absolute():
            continue
        try:
            path.resolve().relative_to(root)
        except ValueError as exc:
            raise AssertionError(f"Path escaped fake project root: {path}") from exc
