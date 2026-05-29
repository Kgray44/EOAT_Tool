from __future__ import annotations

import threading
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

try:
    from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot
except ImportError:  # pragma: no cover
    QObject = QRunnable = QThreadPool = Signal = Slot = None

from core.result import ToolResult

BACKGROUND_TASK_MAX_THREADS = 3


@dataclass(frozen=True)
class TaskRequest:
    id: str
    name: str
    category: str
    callable: Callable[..., Any]
    args: tuple[Any, ...] = ()
    kwargs: dict[str, Any] = field(default_factory=dict)
    modifies_files: bool = False
    requires_workbook_lock: bool = False
    requires_project_lock: bool = False
    user_visible_description: str = ""


@dataclass
class TaskResult:
    id: str
    name: str
    ok: bool
    message: str
    result_data: Any = None
    files_created: list[str] = field(default_factory=list)
    files_modified: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error: str = ""
    traceback_for_debug_log_only: str = ""
    duration_seconds: float = 0.0

    def to_tool_result(self) -> ToolResult:
        if isinstance(self.result_data, ToolResult):
            return self.result_data
        if self.ok:
            return ToolResult.ok(
                self.id,
                self.name,
                self.message,
                warnings=self.warnings,
                files_created=self.files_created,
                files_modified=self.files_modified,
                duration_seconds=self.duration_seconds,
            )
        return ToolResult.fail(
            self.id,
            self.name,
            self.message,
            errors=[self.error] if self.error else [],
            warnings=self.warnings,
            files_created=self.files_created,
            files_modified=self.files_modified,
            duration_seconds=self.duration_seconds,
        )

    def to_markdown(self) -> str:
        return self.to_tool_result().to_markdown()


class ActiveTaskGuard:
    def __init__(self):
        self._lock = threading.Lock()
        self._active_ids: set[str] = set()
        self._active_locks: set[str] = set()

    def _locks_for(self, request: TaskRequest) -> set[str]:
        locks: set[str] = set()
        if request.requires_workbook_lock:
            locks.add("workbook-write")
        if request.requires_project_lock or request.modifies_files:
            locks.add("project-mutation")
        return locks

    def try_start(self, request: TaskRequest) -> tuple[bool, str]:
        requested_locks = self._locks_for(request)
        with self._lock:
            if request.id in self._active_ids:
                return False, f"{request.name} is already running."
            conflict = requested_locks.intersection(self._active_locks)
            if conflict:
                return (
                    False,
                    "Another project-writing task is already running. Wait for it to finish before starting this one.",
                )
            self._active_ids.add(request.id)
            self._active_locks.update(requested_locks)
            return True, ""

    def finish(self, request: TaskRequest) -> None:
        with self._lock:
            self._active_ids.discard(request.id)
            for lock_name in self._locks_for(request):
                self._active_locks.discard(lock_name)


class _TaskSignals(QObject):
    started = Signal(object)
    finished = Signal(object, object)


class _TaskRunnable(QRunnable):
    def __init__(self, request: TaskRequest):
        super().__init__()
        self.request = request
        self.signals = _TaskSignals()

    @Slot()
    def run(self) -> None:
        started = time.perf_counter()
        try:
            self.signals.started.emit(self.request)
        except RuntimeError:
            return
        try:
            value = self.request.callable(*self.request.args, **self.request.kwargs)
            duration = time.perf_counter() - started
            if isinstance(value, ToolResult):
                value.duration_seconds = value.duration_seconds if value.duration_seconds is not None else duration
                result = TaskResult(
                    id=self.request.id,
                    name=self.request.name,
                    ok=value.success,
                    message=value.summary,
                    result_data=value,
                    files_created=value.files_created[:],
                    files_modified=value.files_modified[:],
                    warnings=value.warnings[:],
                    error="; ".join(value.errors),
                    duration_seconds=duration,
                )
            else:
                result = TaskResult(
                    id=self.request.id,
                    name=self.request.name,
                    ok=True,
                    message=f"{self.request.name} completed.",
                    result_data=value,
                    duration_seconds=duration,
                )
        except Exception as exc:  # pragma: no cover - exercised through integration tests
            duration = time.perf_counter() - started
            result = TaskResult(
                id=self.request.id,
                name=self.request.name,
                ok=False,
                message=f"{self.request.name} failed.",
                error=f"{type(exc).__name__}: {exc}",
                traceback_for_debug_log_only=traceback.format_exc(),
                duration_seconds=duration,
            )
        try:
            self.signals.finished.emit(self.request, result)
        except RuntimeError:
            pass


class BackgroundTaskManager(QObject):
    task_started = Signal(object)
    task_finished = Signal(object)
    task_rejected = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.guard = ActiveTaskGuard()
        self.pool = QThreadPool.globalInstance()
        self.pool.setMaxThreadCount(BACKGROUND_TASK_MAX_THREADS)
        self._active_runnables: list[_TaskRunnable] = []

    def run_task(self, request: TaskRequest, on_finished: Callable[[TaskResult], None] | None = None, button=None) -> bool:
        allowed, reason = self.guard.try_start(request)
        if not allowed:
            result = TaskResult(id=request.id, name=request.name, ok=False, message=reason, error=reason)
            self.task_rejected.emit(result)
            if on_finished:
                on_finished(result)
            return False
        if button is not None:
            button.setEnabled(False)
        runnable = _TaskRunnable(request)
        self._active_runnables.append(runnable)
        runnable.signals.started.connect(self.task_started.emit)

        def _finish(req, result):
            self.guard.finish(req)
            if runnable in self._active_runnables:
                self._active_runnables.remove(runnable)
            if button is not None:
                button.setEnabled(True)
            self.task_finished.emit(result)
            if on_finished:
                on_finished(result)

        runnable.signals.finished.connect(_finish)
        self.pool.start(runnable)
        return True


_manager: BackgroundTaskManager | None = None


def get_task_manager() -> BackgroundTaskManager:
    global _manager
    if _manager is None:
        _manager = BackgroundTaskManager()
    return _manager
