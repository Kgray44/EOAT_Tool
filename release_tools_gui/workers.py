"""Explicitly safe worker lifecycle for non-interruptible engine functions."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

from .redaction import redact_text


@dataclass
class CancellationToken:
    requested: bool = False
    started: bool = False

    def cancel(self) -> bool:
        """Cancel only before an engine call begins; never interrupt a safety check mid-flight."""

        if self.started:
            return False
        self.requested = True
        return True


class WorkerSignals(QObject):
    started = Signal(str)
    progress = Signal(str)
    succeeded = Signal(object)
    failed = Signal(str)
    cancelled = Signal(str)
    finished = Signal()


class SafeWorker(QRunnable):
    def __init__(self, name: str, operation: Callable[[], Any]) -> None:
        super().__init__()
        self.name, self.operation, self.signals, self.token = name, operation, WorkerSignals(), CancellationToken()

    @Slot()
    def run(self) -> None:
        if self.token.requested:
            self.signals.cancelled.emit("Cancelled before the read-only engine operation started")
            self.signals.finished.emit()
            return
        self.token.started = True
        self.signals.started.emit(self.name)
        self.signals.progress.emit(
            "Running existing engine function; interruption is intentionally unavailable after start"
        )
        try:
            self.signals.succeeded.emit(self.operation())
        except Exception as exc:  # GUI boundary: no traceback or secret-shaped values leave the worker.
            self.signals.failed.emit(redact_text(exc))
        finally:
            self.signals.finished.emit()


class ToolRunner(QObject):
    """One queued operation per tool page, retaining workers until their terminal signal."""

    state_changed = Signal(bool, str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._pool = QThreadPool.globalInstance()
        self._worker: SafeWorker | None = None

    @property
    def busy(self) -> bool:
        return self._worker is not None

    def submit(
        self,
        name: str,
        operation: Callable[[], Any],
        *,
        succeeded: Callable[[Any], None],
        failed: Callable[[str], None],
        cancelled: Callable[[str], None],
    ) -> bool:
        if self._worker is not None:
            return False
        worker = SafeWorker(name, operation)
        self._worker = worker
        worker.signals.succeeded.connect(succeeded)
        worker.signals.failed.connect(failed)
        worker.signals.cancelled.connect(cancelled)
        worker.signals.finished.connect(self._finished)
        self.state_changed.emit(True, name)
        self._pool.start(worker)
        return True

    def request_cancel(self) -> bool:
        return bool(self._worker and self._worker.token.cancel())

    def _finished(self) -> None:
        self._worker = None
        self.state_changed.emit(False, "")
