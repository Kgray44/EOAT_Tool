from __future__ import annotations

from datetime import datetime, timezone
from time import monotonic

from PySide6.QtTest import QTest

from core.data_freshness import DataFreshnessService, FreshnessSettings
from core.data_freshness_qt import DataStatusPollWorker, QtDataFreshnessPoller


def _payload(revision: int = 7) -> dict[str, object]:
    return {
        "status": "available",
        "data_revision": revision,
        "data_last_modified_at": "2026-07-21T14:18:43.128Z",
        "last_import_at": "2026-07-21T12:42:11.002Z",
        "last_import_source": "qt-lifecycle-test",
        "server_time": "2026-07-21T14:19:02.415Z",
        "source": "mysql",
        "environment": "test",
    }


def _wait_for(qapp, condition, *, timeout_seconds: float = 3.0) -> None:
    """Deliberately pump the shared test event loop until one bounded condition is true."""
    deadline = monotonic() + timeout_seconds
    while monotonic() < deadline:
        qapp.processEvents()
        if condition():
            return
        QTest.qWait(10)
    assert condition()


def test_poller_finishes_worker_thread_before_shutdown(qapp, monkeypatch, tmp_path) -> None:
    def succeed(worker: DataStatusPollWorker) -> None:
        worker.succeeded.emit(_payload(), datetime.now(timezone.utc))

    monkeypatch.setattr(DataStatusPollWorker, "run", succeed)
    service = DataFreshnessService(
        settings=FreshnessSettings(polling_interval_seconds=15),
    )
    poller = QtDataFreshnessPoller(service)
    transitions: list[str] = []
    poller.transitioned.connect(lambda _service, transition: transitions.append(transition.kind))

    poller.start(immediate=True)
    _wait_for(qapp, lambda: bool(transitions) and not service.check_active)

    assert transitions == ["initial"]
    assert service.last_checked_at is not None
    assert poller._timer.isActive()
    thread = poller._thread
    assert thread is not None and thread.isRunning()

    poller.shutdown()
    assert poller._thread is None
    assert not poller._timer.isActive()
    assert not thread.isRunning()


def test_disabled_poller_allows_one_manual_check_without_creating_a_timer(qapp, monkeypatch) -> None:
    def succeed(worker: DataStatusPollWorker) -> None:
        worker.succeeded.emit(_payload(), datetime.now(timezone.utc))

    monkeypatch.setattr(DataStatusPollWorker, "run", succeed)
    service = DataFreshnessService(
        settings=FreshnessSettings(automatic_polling_enabled=False),
    )
    poller = QtDataFreshnessPoller(service)

    poller.start(immediate=True)
    assert not poller._timer.isActive()
    assert poller.check_now()
    _wait_for(qapp, lambda: not service.check_active and service.last_checked_at is not None)

    assert not poller._timer.isActive()
    thread = poller._thread
    assert thread is not None and thread.isRunning()
    poller.shutdown()
    assert not thread.isRunning()


def test_repeated_poller_checks_reuse_one_thread_and_shutdown_cleanly(qapp, monkeypatch) -> None:
    revision = {"value": 0}

    def succeed(worker: DataStatusPollWorker) -> None:
        revision["value"] += 1
        worker.succeeded.emit(_payload(revision["value"]), datetime.now(timezone.utc))

    monkeypatch.setattr(DataStatusPollWorker, "run", succeed)
    service = DataFreshnessService(settings=FreshnessSettings(automatic_polling_enabled=False))
    poller = QtDataFreshnessPoller(service)
    thread = None
    for expected_revision in range(1, 13):
        assert poller.check_now()
        _wait_for(
            qapp,
            lambda expected_revision=expected_revision: not service.check_active
            and service.current_revision == expected_revision,
        )
        assert poller._thread is not None and poller._thread.isRunning()
        if thread is None:
            thread = poller._thread
        assert poller._thread is thread
        assert poller._worker is not None
        assert not poller._timer.isActive()

    poller.shutdown()
    assert thread is not None and not thread.isRunning()
    assert poller._thread is None
    assert poller._worker is None


def test_resume_after_a_long_gap_runs_one_safe_check_without_replaying_missed_intervals(qapp, monkeypatch) -> None:
    """Resume/focus is one immediate safety check, never a catch-up burst."""
    calls = {"count": 0}

    def succeed(worker: DataStatusPollWorker) -> None:
        calls["count"] += 1
        worker.succeeded.emit(_payload(calls["count"]), datetime.now(timezone.utc))

    monkeypatch.setattr(DataStatusPollWorker, "run", succeed)
    service = DataFreshnessService(settings=FreshnessSettings(polling_interval_seconds=60))
    poller = QtDataFreshnessPoller(service)
    poller.start(immediate=True)
    _wait_for(qapp, lambda: calls["count"] == 1 and not service.check_active)
    worker_thread = poller._thread

    # Multiple focus notifications during resume are possible on Windows. The
    # first starts one request; the remaining notifications observe it active.
    poller.resume_or_focus()
    poller.resume_or_focus()
    poller.resume_or_focus()
    _wait_for(qapp, lambda: calls["count"] == 2 and not service.check_active)
    QTest.qWait(80)
    qapp.processEvents()

    assert calls["count"] == 2
    assert service.current_revision == 2
    assert poller._thread is worker_thread
    assert worker_thread is not None and worker_thread.isRunning()
    assert poller._timer.isActive()

    poller.shutdown()
    assert not worker_thread.isRunning()
