"""Qt execution adapter for the GUI-independent data freshness state model."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timezone

from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot

from .data_freshness import DataFreshnessService, FreshnessProtocolError
from .data_gateway.api_client import AtlasApiClient
from .data_gateway.cache_repository import CacheRepository
from .data_gateway.configuration import GatewayConfiguration

LOGGER = logging.getLogger(__name__)


class DataStatusPollWorker(QObject):
    succeeded = Signal(object, object)
    failed = Signal(str)

    def __init__(self, configuration: GatewayConfiguration, timeout_seconds: int):
        super().__init__()
        self.configuration = replace(configuration, timeout_seconds=float(timeout_seconds))

    @Slot()
    def run(self) -> None:
        client = AtlasApiClient(
            self.configuration.api_base_url,
            timeout=self.configuration.timeout_seconds,
            identity=self.configuration.development_identity,
            application_instance_id=self.configuration.application_instance_id,
            client_version=self.configuration.client_version,
        )
        try:
            self.succeeded.emit(client.data_status(), datetime.now(timezone.utc))
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")
        finally:
            client.close()


class QtDataFreshnessPoller(QObject):
    """Runs at most one lightweight status request and schedules bounded retries."""

    transitioned = Signal(object, object)
    poll_failed = Signal(str)
    poll_requested = Signal()

    def __init__(
        self,
        service: DataFreshnessService,
        *,
        configuration: GatewayConfiguration | None = None,
        can_poll: Callable[[], bool] | None = None,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self.service = service
        self.configuration = configuration or GatewayConfiguration.from_environment()
        self.can_poll = can_poll or (lambda: True)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._scheduled_check)
        self._thread: QThread | None = None
        self._worker: DataStatusPollWorker | None = None
        self._shutting_down = False
        self._resume_check_queued = False

    def start(self, *, immediate: bool = False) -> None:
        if self._shutting_down:
            return
        if not self.service.settings.automatic_polling_enabled:
            self._timer.stop()
            return
        self._schedule(0 if immediate else self.service.next_delay_seconds)

    def reconfigure(self) -> None:
        self._timer.stop()
        self.start(immediate=False)

    def check_now(self) -> bool:
        """Request one manual check without changing the normal schedule."""
        if self._shutting_down or self.service.check_active:
            return False
        return self._start_worker(manual=True)

    def resume_or_focus(self) -> None:
        """Coalesce a Windows resume/focus burst into one safe status check."""
        if self._shutting_down or self.service.check_active or self._resume_check_queued:
            return
        self._resume_check_queued = True
        QTimer.singleShot(0, self, self._run_resumed_check)

    @Slot()
    def _run_resumed_check(self) -> None:
        self._resume_check_queued = False
        if not self.service.check_active and not self._shutting_down:
            self._start_worker(manual=False)

    def shutdown(self) -> None:
        self._shutting_down = True
        self._resume_check_queued = False
        self._timer.stop()
        self.service.shutdown()
        thread = self._thread
        if thread is not None and thread.isRunning():
            # ``QThread`` is owned by this poller.  Request its event loop to
            # exit before waiting so its parent cannot be destroyed while an
            # in-flight status request still owns a native thread.
            thread.quit()
            thread.wait()
        self._worker = None
        self._thread = None

    @Slot()
    def _scheduled_check(self) -> None:
        if self._shutting_down:
            return
        if not self.can_poll():
            self._schedule(self.service.next_delay_seconds)
            return
        if not self._start_worker(manual=False):
            self._schedule(self.service.next_delay_seconds)

    def _start_worker(self, *, manual: bool) -> bool:
        if not self.service.begin_check(manual=manual):
            return False
        self._timer.stop()
        self._ensure_worker_thread()
        self.poll_requested.emit()
        return True

    def _ensure_worker_thread(self) -> None:
        """Create one poller-owned event-loop thread and reuse it for status checks.

        Starting and deleting a short-lived ``QThread`` for every poll caused
        PySide to dispatch deletion while its native ``finished`` signal was
        still active under cumulative Qt test load.  A poller has one owner
        and one outstanding request by design, so one persistent worker thread
        provides the same serial I/O contract without per-poll destruction.
        """
        if self._thread is not None and self._thread.isRunning() and self._worker is not None:
            return
        thread = QThread(self)
        worker = DataStatusPollWorker(self.configuration, self.service.settings.request_timeout_seconds)
        worker.moveToThread(thread)
        self.poll_requested.connect(worker.run)
        worker.succeeded.connect(self._poll_succeeded)
        worker.failed.connect(self._poll_failed)
        thread.finished.connect(worker.deleteLater)
        self._thread = thread
        self._worker = worker
        thread.start()

    @Slot(object, object)
    def _poll_succeeded(self, payload: dict, received_at: datetime) -> None:
        if self._shutting_down:
            return
        try:
            transition = self.service.receive_status(payload, received_at=received_at)
            self._persist_status(payload)
            if abs(self.service.clock_offset_seconds or 0) >= 300:
                LOGGER.warning(
                    "data_freshness_clock_drift seconds=%s", round(self.service.clock_offset_seconds or 0, 1)
                )
            if transition.kind != "unchanged":
                LOGGER.info("data_freshness_transition kind=%s revision=%s", transition.kind, transition.revision)
            else:
                LOGGER.debug("data_freshness_unchanged revision=%s", transition.revision)
            self.transitioned.emit(self.service, transition)
        except FreshnessProtocolError as exc:
            self.service.record_failure(exc)
            LOGGER.warning("data_freshness_protocol_error error=%s", exc)
            self.poll_failed.emit(str(exc))
        finally:
            if not self._shutting_down:
                self._schedule(self.service.next_delay_seconds)

    @Slot(str)
    def _poll_failed(self, message: str) -> None:
        if self._shutting_down:
            return
        self.service.record_failure(message)
        LOGGER.warning("data_freshness_poll_failed failures=%s error=%s", self.service.consecutive_failures, message)
        self.poll_failed.emit(message)
        if not self._shutting_down:
            self._schedule(self.service.next_delay_seconds)

    def _schedule(self, seconds: int) -> None:
        if self._shutting_down or not self.service.settings.automatic_polling_enabled:
            return
        self._timer.start(max(0, int(seconds)) * 1000)

    def _persist_status(self, payload: dict) -> None:
        # The disposable cache is a restart-safe client record, not authority.
        CacheRepository(self.configuration.cache_path).update_diagnostics(
            {
                "data_revision": payload.get("data_revision", ""),
                "data_last_modified_at": payload.get("data_last_modified_at", ""),
                "last_import_at": payload.get("last_import_at", ""),
                "last_import_source": payload.get("last_import_source", ""),
                "last_successful_data_status_check_at": self.service.last_checked_at.isoformat()
                if self.service.last_checked_at
                else "",
            }
        )


__all__ = ["DataStatusPollWorker", "QtDataFreshnessPoller"]
