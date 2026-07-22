"""Qt worker primitives that keep every service operation off the GUI thread."""

from __future__ import annotations

import traceback
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot


class WorkerSignals(QObject):
    started = Signal(str)
    succeeded = Signal(object)
    failed = Signal(str, str)
    finished = Signal()


class ServiceWorker(QRunnable):
    def __init__(self, name: str, operation: Callable[[], Any]) -> None:
        super().__init__()
        self.name, self.operation, self.signals = name, operation, WorkerSignals()

    @Slot()
    def run(self) -> None:
        self.signals.started.emit(self.name)
        try:
            self.signals.succeeded.emit(self.operation())
        except Exception as exc:  # backend exceptions are normalized for the operator by windows
            self.signals.failed.emit(str(exc), traceback.format_exc())
        finally:
            self.signals.finished.emit()


class BackgroundRunner(QObject):
    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.pool = QThreadPool.globalInstance()
        self._workers: set[ServiceWorker] = set()

    def submit(
        self,
        name: str,
        operation: Callable[[], Any],
        *,
        success: Callable[[Any], None],
        failure: Callable[[str, str], None],
        finished: Callable[[], None],
    ) -> None:
        worker = ServiceWorker(name, operation)
        self._workers.add(worker)
        worker.signals.succeeded.connect(success)
        worker.signals.failed.connect(failure)
        worker.signals.finished.connect(lambda: self._finish_worker(worker, finished))
        self.pool.start(worker)

    def _finish_worker(self, worker: ServiceWorker, finished: Callable[[], None]) -> None:
        self._workers.discard(worker)
        finished()
