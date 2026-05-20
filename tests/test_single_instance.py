from __future__ import annotations

import os
import uuid

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.single_instance import SingleInstanceGuard


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_single_instance_guard_rejects_second_guard():
    _app()
    name = f"EOAT_Command_Center_Test_{uuid.uuid4().hex}"
    first = SingleInstanceGuard(name)
    second = SingleInstanceGuard(name)
    try:
        assert first.acquire()
        assert not second.acquire()
    finally:
        first.release()
        second.release()


def test_single_instance_guard_releases_cleanly():
    _app()
    name = f"EOAT_Command_Center_Test_{uuid.uuid4().hex}"
    first = SingleInstanceGuard(name)
    second = SingleInstanceGuard(name)
    try:
        assert first.acquire()
        first.release()
        assert second.acquire()
    finally:
        first.release()
        second.release()
