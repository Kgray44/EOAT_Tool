from __future__ import annotations

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from app.task_runner import ActiveTaskGuard, BackgroundTaskManager, TaskRequest


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _wait_for_task(manager: BackgroundTaskManager, request: TaskRequest, timeout_ms: int = 3000):
    _app()
    loop = QEventLoop()
    results = []

    def _done(result):
        results.append(result)
        loop.quit()

    assert manager.run_task(request, on_finished=_done)
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()
    assert results
    return results[0]


def test_background_task_success_and_failure():
    manager = BackgroundTaskManager()
    ok = _wait_for_task(manager, TaskRequest("dummy_ok", "Dummy OK", "test", lambda: "done"))
    assert ok.ok
    assert ok.result_data == "done"

    failed = _wait_for_task(manager, TaskRequest("dummy_fail", "Dummy Fail", "test", lambda: (_ for _ in ()).throw(ValueError("boom"))))
    assert not failed.ok
    assert "ValueError" in failed.error


def test_task_guard_rejects_conflicting_workbook_writes():
    guard = ActiveTaskGuard()
    first = TaskRequest("write_one", "Write One", "test", lambda: None, modifies_files=True, requires_workbook_lock=True)
    second = TaskRequest("write_two", "Write Two", "test", lambda: None, modifies_files=True, requires_workbook_lock=True)

    allowed, reason = guard.try_start(first)
    assert allowed
    allowed, reason = guard.try_start(second)
    assert not allowed
    assert "project-writing task" in reason
    guard.finish(first)
    allowed, _reason = guard.try_start(second)
    assert allowed
    guard.finish(second)


def test_task_manager_rejects_duplicate_active_id():
    manager = BackgroundTaskManager()
    request = TaskRequest("duplicate", "Duplicate", "test", lambda: time.sleep(0.2))
    assert manager.run_task(request)
    rejected = []
    assert not manager.run_task(request, on_finished=lambda result: rejected.append(result))
    assert rejected and not rejected[0].ok
