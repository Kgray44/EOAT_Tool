from __future__ import annotations

import logging
import os
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PySide6.QtCore import QCoreApplication, QEvent, QObject, QRunnable, QSize, Qt, QThreadPool, QTimer, Signal, Slot
from PySide6.QtGui import QImage, QImageReader

LOGGER = logging.getLogger(__name__)

SUPPORTED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}
PRELOAD_MODES = ("off", "conservative", "balanced", "aggressive")
FULL_PRELOAD_SIZE = QSize(960, 640)
THUMB_PRELOAD_SIZE = QSize(220, 150)


@dataclass(frozen=True)
class PhotoLoadResult:
    path: str
    image: QImage
    state: str
    message: str = ""
    detail: str = ""
    decode_ms: float = 0.0
    from_cache: bool = False


@dataclass(frozen=True)
class _PhotoJob:
    cache_key: tuple
    path: str
    requested_size: QSize
    priority: int
    reason: str
    sequence: int


class _PhotoWorkerSignals(QObject):
    finished = Signal(tuple, object)


class _PhotoDecodeTask(QRunnable):
    def __init__(self, cache_key: tuple, path: str, requested_size: QSize):
        super().__init__()
        self.cache_key = cache_key
        self.path = path
        self.requested_size = QSize(requested_size)
        self.signals = _PhotoWorkerSignals()

    @Slot()
    def run(self) -> None:
        self.signals.finished.emit(self.cache_key, decode_photo_image(self.path, self.requested_size))


class PhotoLoadManager(QObject):
    image_ready = Signal(str, object)

    CACHE_FULL_MESSAGE = "Photo cache full. Additional photos will not be queued until cache space is available."

    def __init__(self, parent=None, *, max_entries: int = 384, max_memory_mb: int = 1024):
        super().__init__(parent)
        self.max_entries = max_entries
        self.max_memory_bytes = max(32, int(max_memory_mb)) * 1024 * 1024
        self.max_active_workers = 2
        self.max_active_preload_workers = 1
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(self.max_active_workers)
        self.preload_mode = "conservative"
        self._cache: OrderedDict[tuple, PhotoLoadResult] = OrderedDict()
        self._cache_memory_bytes_total = 0
        self._pending: dict[tuple, list[str]] = {}
        self._request_keys: dict[str, tuple] = {}
        self._workers: dict[tuple, _PhotoDecodeTask] = {}
        self._worker_priorities: dict[tuple, int] = {}
        self._job_queue: list[_PhotoJob] = []
        self._queued_keys: set[tuple] = set()
        self._sequence = 0
        self._failed_loads = 0
        self._last_decode_ms = 0.0
        self._last_lag_ms = 0.0
        self._last_activity = time.perf_counter()
        self._last_heartbeat = time.perf_counter()
        self._ui_ready_for_preload = False
        self._app_active = True
        self._last_preload_reason = "Paused: app loading"
        self._last_completed_file = ""
        self._last_preload_drop = 0.0
        self._catalog_paths: tuple[str, ...] = ()
        self._catalog_cursor = 0
        self._visible_paths: tuple[str, ...] = ()
        self._selected_paths: tuple[str, ...] = ()
        self._related_paths: tuple[str, ...] = ()
        self._activity_event_types = {
            QEvent.Type.ApplicationActivate,
            QEvent.Type.FocusIn,
            QEvent.Type.KeyPress,
            QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseButtonRelease,
            QEvent.Type.MouseMove,
            QEvent.Type.TouchBegin,
            QEvent.Type.Wheel,
            QEvent.Type.WindowActivate,
        }
        self._heartbeat_interval_ms = 150
        self._heartbeat = QTimer(self)
        self._heartbeat.setInterval(self._heartbeat_interval_ms)
        self._heartbeat.timeout.connect(self._record_event_loop_lag)
        self._heartbeat.start()
        self._scheduler = QTimer(self)
        self._scheduler.setInterval(350)
        self._scheduler.timeout.connect(self._scheduler_tick)
        self._scheduler.start()
        app = QCoreApplication.instance()
        self._event_filter_app = app
        if app is not None:
            app.installEventFilter(self)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        event_type = event.type()
        if event_type == QEvent.Type.ApplicationDeactivate:
            self._app_active = False
            self._drop_queued_preloads()
            self._last_preload_reason = "Paused: app inactive"
        elif event_type in self._activity_event_types:
            self._app_active = True
            self.mark_user_activity()
        return super().eventFilter(watched, event)

    def set_preload_mode(self, mode: str) -> None:
        normalized = str(mode or "").casefold().replace(" ", "_").replace("-", "_")
        self.preload_mode = normalized if normalized in PRELOAD_MODES else "conservative"
        if self.preload_mode == "off":
            self._last_preload_reason = "Off: preload disabled"
        elif not self._ui_ready_for_preload:
            self._last_preload_reason = "Paused: app loading"
        else:
            self._last_preload_reason = "Ready"
        QTimer.singleShot(0, self._dispatch_jobs)

    def set_cache_limit_mb(self, limit_mb: int) -> None:
        self.max_memory_bytes = max(32, int(limit_mb or 1024)) * 1024 * 1024
        self._enforce_cache_budget()
        if self._cache_is_full():
            self._pause_for_full_cache()
            return
        if "cache full" in self._last_preload_reason.casefold():
            self._last_preload_reason = "Ready"
        QTimer.singleShot(0, self._dispatch_jobs)

    def set_ui_ready_for_preload(self, ready: bool = True, *, reason: str = "") -> None:
        self._ui_ready_for_preload = bool(ready)
        if self._ui_ready_for_preload:
            self._last_activity = time.perf_counter()
            self._last_preload_reason = reason or ("Off: preload disabled" if self.preload_mode == "off" else "Ready")
            QTimer.singleShot(0, self._dispatch_jobs)
            return
        self._drop_queued_preloads()
        self._last_preload_reason = reason or "Paused: app loading"

    def set_photo_catalog(self, bundle_or_records: Any) -> None:
        records = getattr(bundle_or_records, "eoats", bundle_or_records) or ()
        self._catalog_paths = tuple(_unique_photo_paths(records))
        self._catalog_cursor = 0
        if self.preload_mode != "off" and self._ui_ready_for_preload:
            self._last_preload_reason = "Ready"

    def update_visible_photo_context(self, records: Any, *, reason: str = "Idle preload: visible photo library") -> None:
        self._visible_paths = tuple(_unique_photo_paths(records))
        if self._visible_paths and self._ui_ready_for_preload:
            self._last_preload_reason = reason

    def update_selected_photo_context(self, record: Any | None, *, reason: str = "Idle preload: selected EOAT") -> None:
        self._selected_paths = tuple(_unique_photo_paths([record] if record is not None else []))
        if self._selected_paths and self._ui_ready_for_preload:
            self._last_preload_reason = reason

    def update_related_photo_paths(self, paths: Any, *, reason: str = "Idle preload: related EOATs") -> None:
        self._related_paths = tuple(_unique_existing_image_paths(paths))
        if self._related_paths and self._ui_ready_for_preload:
            self._last_preload_reason = reason

    def prime_photo_cache(self, *, limit: int = 48) -> int:
        if not self._ui_ready_for_preload:
            self._last_preload_reason = "Paused: app loading"
            return 0
        if self._cache_is_full():
            self._pause_for_full_cache()
            return 0
        paths = (*self._selected_paths, *self._visible_paths, *self._related_paths, *self._catalog_window(limit))
        queued = self._queue_preload_paths(paths, priority=5, reason="Manual prime photo cache", limit=limit)
        self._dispatch_jobs()
        return queued

    def mark_user_activity(self) -> None:
        now = time.perf_counter()
        self._last_activity = now
        if now - self._last_preload_drop < 0.2:
            return
        if any(job.priority > 0 for job in self._job_queue):
            self._drop_queued_preloads()
            self._last_preload_drop = now
            self._last_preload_reason = "Paused: user active"

    def clear_cache(self) -> None:
        self._cache.clear()
        self._cache_memory_bytes_total = 0
        self._last_preload_reason = "Cleared"
        QTimer.singleShot(0, self._dispatch_jobs)

    def request_image(
        self,
        path: str,
        *,
        request_id: str,
        requested_size: QSize | None = None,
        priority: int = 0,
        reason: str = "",
        force_preload: bool = False,
    ) -> None:
        requested_size = requested_size or QSize()
        target = Path(path)
        cache_key = _cache_key(target, requested_size)
        self._request_keys[request_id] = cache_key
        cached = self._cache.get(cache_key)
        if cached is not None:
            self._cache.move_to_end(cache_key)
            QTimer.singleShot(0, lambda: self.image_ready.emit(request_id, _copy_result(cached, from_cache=True)))
            return
        if priority > 0 and not self._ui_ready_for_preload and not force_preload:
            self._last_preload_reason = "Paused: app loading"
            self._request_keys.pop(request_id, None)
            return
        if priority > 0 and self.preload_mode == "off" and not force_preload:
            self._last_preload_reason = "Off: preload disabled"
            self._request_keys.pop(request_id, None)
            return
        if self._cache_is_full():
            if priority > 0 or force_preload:
                self._request_keys.pop(request_id, None)
                self._pause_for_full_cache()
                return
            self._make_cache_room()
            if self._cache_is_full():
                self._request_keys.pop(request_id, None)
                self._last_preload_reason = self.CACHE_FULL_MESSAGE
                return
        if cache_key in self._pending:
            self._pending[cache_key].append(request_id)
            if priority == 0:
                self._promote_queued_job(cache_key, requested_size, reason or "Photo load")
                self._dispatch_jobs(force=True)
            return
        self._pending[cache_key] = [request_id]
        self._enqueue_job(cache_key, str(target), requested_size, priority, reason or _priority_reason(priority))
        self._dispatch_jobs(force=priority == 0)

    def cancel_request(self, request_id: str) -> None:
        cache_key = self._request_keys.pop(request_id, None)
        if cache_key is None:
            return
        waiting = self._pending.get(cache_key)
        if waiting and request_id in waiting:
            waiting.remove(request_id)

    def stats(self) -> dict[str, object]:
        memory_bytes = self._cache_memory_bytes()
        thumbnail_entries = sum(1 for key in self._cache if _cache_key_is_thumbnail(key))
        full_entries = max(0, len(self._cache) - thumbnail_entries)
        return {
            "cache_entries": len(self._cache),
            "decoded_images": len(self._cache),
            "thumbnail_entries": thumbnail_entries,
            "full_entries": full_entries,
            "cache_memory_mb": round(memory_bytes / (1024 * 1024), 1),
            "cache_memory_limit_mb": round(self.max_memory_bytes / (1024 * 1024), 1),
            "jobs_queued": len(self._job_queue),
            "active_jobs": len(self._workers),
            "worker_limit": self.max_active_workers,
            "last_decode_ms": round(self._last_decode_ms, 1),
            "failed_loads": self._failed_loads,
            "event_loop_lag_ms": round(self._last_lag_ms, 1),
            "idle": self._allow_preload(),
            "app_active": self._app_active,
            "ui_ready_for_preload": self._ui_ready_for_preload,
            "preload_mode": self.preload_mode,
            "last_preload_reason": self._last_preload_reason,
            "last_completed_file": self._last_completed_file,
            "cache_full": self._cache_is_full(),
            "cache_status": self._cache_status(),
        }

    def _scheduler_tick(self) -> None:
        if not self._ui_ready_for_preload:
            self._last_preload_reason = "Paused: app loading"
            return
        self._dispatch_jobs()
        if self._cache_is_full():
            self._pause_for_full_cache()
            return
        if self.preload_mode == "off":
            self._last_preload_reason = "Off: preload disabled"
            return
        if self._job_queue or self._workers:
            return
        if not self._allow_preload():
            self._last_preload_reason = self._preload_pause_reason()
            return
        queued = self._queue_idle_preload_batch()
        if queued:
            self._dispatch_jobs()

    def _queue_idle_preload_batch(self) -> int:
        if self._cache_is_full():
            self._pause_for_full_cache()
            return 0
        mode_limits = {
            "conservative": (4, 0, 0, 0),
            "balanced": (6, 8, 6, 0),
            "aggressive": (8, 8, 8, 10),
        }
        selected_limit, visible_limit, related_limit, catalog_limit = mode_limits.get(self.preload_mode, mode_limits["conservative"])
        queued = self._queue_preload_paths(
            self._selected_paths,
            priority=3,
            reason="Idle preload: selected EOAT",
            limit=selected_limit,
        )
        if queued:
            return queued
        if visible_limit:
            queued = self._queue_preload_paths(
                self._visible_paths,
                priority=3,
                reason="Idle preload: visible photo library",
                limit=visible_limit,
            )
            if queued:
                return queued
        if related_limit:
            queued = self._queue_preload_paths(
                self._related_paths,
                priority=4,
                reason="Idle preload: related EOATs",
                limit=related_limit,
            )
            if queued:
                return queued
        if catalog_limit:
            queued = self._queue_preload_paths(
                self._catalog_window(catalog_limit),
                priority=5,
                reason="Idle preload: other EOAT photo sets",
                limit=catalog_limit,
            )
            if queued:
                return queued
        self._last_preload_reason = "Ready"
        return 0

    def _catalog_window(self, limit: int) -> tuple[str, ...]:
        if not self._catalog_paths or limit <= 0:
            return ()
        paths: list[str] = []
        attempts = 0
        while len(paths) < limit and attempts < len(self._catalog_paths):
            path = self._catalog_paths[self._catalog_cursor % len(self._catalog_paths)]
            self._catalog_cursor = (self._catalog_cursor + 1) % len(self._catalog_paths)
            attempts += 1
            paths.append(path)
        return tuple(paths)

    def _queue_preload_paths(
        self,
        paths: Any,
        *,
        priority: int,
        reason: str,
        limit: int,
        force: bool = False,
    ) -> int:
        if limit <= 0:
            return 0
        queued = 0
        for path in _unique_existing_image_paths(paths):
            if queued >= limit:
                break
            if self._cache_is_full():
                self._pause_for_full_cache()
                break
            cache_key = _cache_key(Path(path), FULL_PRELOAD_SIZE)
            if cache_key in self._cache or cache_key in self._queued_keys or cache_key in self._workers:
                continue
            request_id = f"__preload:{priority}:{self._sequence}:{time.perf_counter_ns()}"
            self.request_image(
                path,
                request_id=request_id,
                requested_size=FULL_PRELOAD_SIZE,
                priority=priority,
                reason=reason,
                force_preload=force,
            )
            queued += 1
        if queued:
            self._last_preload_reason = reason
        return queued

    def _enqueue_job(self, cache_key: tuple, path: str, requested_size: QSize, priority: int, reason: str) -> None:
        if cache_key in self._cache or cache_key in self._queued_keys or cache_key in self._workers:
            return
        self._sequence += 1
        self._job_queue.append(_PhotoJob(cache_key, path, QSize(requested_size), priority, reason, self._sequence))
        self._queued_keys.add(cache_key)
        self._job_queue.sort(key=lambda job: (job.priority, job.sequence))
        if priority > 0:
            self._last_preload_reason = reason

    def _promote_queued_job(self, cache_key: tuple, requested_size: QSize, reason: str) -> bool:
        for index, job in enumerate(self._job_queue):
            if job.cache_key != cache_key or job.priority == 0:
                continue
            self._job_queue[index] = _PhotoJob(
                cache_key=job.cache_key,
                path=job.path,
                requested_size=QSize(requested_size) if requested_size.isValid() else job.requested_size,
                priority=0,
                reason=reason,
                sequence=job.sequence,
            )
            self._job_queue.sort(key=lambda queued: (queued.priority, queued.sequence))
            return True
        return False

    def _drop_queued_preloads(self) -> None:
        kept: list[_PhotoJob] = []
        for job in self._job_queue:
            if job.priority > 0:
                self._queued_keys.discard(job.cache_key)
                self._pending.pop(job.cache_key, None)
                continue
            kept.append(job)
        self._job_queue = kept

    def _dispatch_jobs(self, *, force: bool = False) -> None:
        if self._cache_is_full():
            self._pause_for_full_cache()
        while self._job_queue and len(self._workers) < self.max_active_workers:
            job = self._next_dispatchable_job(force=force)
            if job is None:
                return
            if job.priority > 0 and not force:
                if not self._allow_preload():
                    self._last_preload_reason = self._preload_pause_reason()
                    return
                if self._cache_is_full():
                    self._pause_for_full_cache()
                    return
            self._job_queue.remove(job)
            self._queued_keys.discard(job.cache_key)
            worker = _PhotoDecodeTask(job.cache_key, job.path, job.requested_size)
            worker.signals.finished.connect(self._worker_finished)
            self._workers[job.cache_key] = worker
            self._worker_priorities[job.cache_key] = job.priority
            self._last_preload_reason = job.reason
            self.pool.start(worker)

    def _next_dispatchable_job(self, *, force: bool) -> _PhotoJob | None:
        for job in self._job_queue:
            if job.priority == 0:
                return job
        if force:
            return self._job_queue[0]
        if self._active_preload_workers() >= self.max_active_preload_workers:
            return None
        if len(self._workers) >= self.max_active_workers - 1:
            return None
        for job in self._job_queue:
            if job.priority > 0:
                return job
        return None

    def _active_preload_workers(self) -> int:
        return sum(1 for priority in self._worker_priorities.values() if priority > 0)

    def _allow_preload(self) -> bool:
        if not self._ui_ready_for_preload:
            return False
        if not self._app_active:
            return False
        if self.preload_mode == "off":
            return False
        now = time.perf_counter()
        idle_threshold = {"conservative": 2.0, "balanced": 1.5, "aggressive": 1.0}.get(self.preload_mode, 2.0)
        lag_threshold_ms = {"conservative": 45, "balanced": 60, "aggressive": 80}.get(self.preload_mode, 45)
        return now - self._last_activity >= idle_threshold and self._last_lag_ms <= lag_threshold_ms and not self._cache_is_full()

    def _preload_pause_reason(self) -> str:
        if not self._ui_ready_for_preload:
            return "Paused: app loading"
        if not self._app_active:
            return "Paused: app inactive"
        if self.preload_mode == "off":
            return "Off: preload disabled"
        now = time.perf_counter()
        idle_threshold = {"conservative": 2.0, "balanced": 1.5, "aggressive": 1.0}.get(self.preload_mode, 2.0)
        lag_threshold_ms = {"conservative": 45, "balanced": 60, "aggressive": 80}.get(self.preload_mode, 45)
        if now - self._last_activity < idle_threshold:
            return "Paused: user active"
        if self._last_lag_ms > lag_threshold_ms:
            return "Paused: event-loop lag"
        if self._cache_is_full():
            return "Paused: cache full"
        return "Ready"

    @Slot()
    def _record_event_loop_lag(self) -> None:
        now = time.perf_counter()
        elapsed_ms = (now - self._last_heartbeat) * 1000
        self._last_heartbeat = now
        self._last_lag_ms = max(0.0, elapsed_ms - self._heartbeat_interval_ms)

    @Slot(tuple, object)
    def _worker_finished(self, cache_key: tuple, result: PhotoLoadResult) -> None:
        self._workers.pop(cache_key, None)
        self._worker_priorities.pop(cache_key, None)
        self._last_decode_ms = result.decode_ms
        self._last_completed_file = Path(result.path).name if result.path else ""
        if result.state != "loaded":
            self._failed_loads += 1
        if result.state == "loaded":
            self._store_cache_result(cache_key, result)
            self._enforce_cache_budget()
        request_ids = self._pending.pop(cache_key, [])
        for request_id in request_ids:
            self._request_keys.pop(request_id, None)
            self.image_ready.emit(request_id, result)
        QTimer.singleShot(0, self._dispatch_jobs)

    def _store_cache_result(self, cache_key: tuple, result: PhotoLoadResult) -> None:
        previous = self._cache.get(cache_key)
        if previous is not None:
            self._cache_memory_bytes_total -= _cache_result_bytes(previous)
        self._cache[cache_key] = result
        self._cache_memory_bytes_total += _cache_result_bytes(result)
        self._cache.move_to_end(cache_key)

    def _enforce_cache_budget(self) -> None:
        while len(self._cache) > self.max_entries:
            _key, result = self._cache.popitem(last=False)
            self._cache_memory_bytes_total -= _cache_result_bytes(result)
        while self._cache and self._cache_memory_bytes() > self.max_memory_bytes:
            _key, result = self._cache.popitem(last=False)
            self._cache_memory_bytes_total -= _cache_result_bytes(result)
        self._cache_memory_bytes_total = max(0, self._cache_memory_bytes_total)

    def _make_cache_room(self) -> None:
        while self._cache and (len(self._cache) >= self.max_entries or self._cache_memory_bytes() >= self.max_memory_bytes):
            _key, result = self._cache.popitem(last=False)
            self._cache_memory_bytes_total -= _cache_result_bytes(result)
        self._cache_memory_bytes_total = max(0, self._cache_memory_bytes_total)

    def _pause_for_full_cache(self) -> None:
        self._drop_queued_preloads()
        self._last_preload_reason = self.CACHE_FULL_MESSAGE

    def _cache_memory_bytes(self) -> int:
        return max(0, self._cache_memory_bytes_total)

    def _cache_is_full(self) -> bool:
        return len(self._cache) >= self.max_entries or self._cache_memory_bytes() >= self.max_memory_bytes

    def _cache_status(self) -> str:
        lowered = self._last_preload_reason.casefold()
        if self._cache_is_full():
            return "Cache full"
        if self._workers or self._job_queue:
            return "Loading photos"
        if "cleared" in lowered:
            return "Cleared"
        if "error" in lowered or self._failed_loads:
            return "Error" if "failed" in lowered else "Ready"
        if lowered.startswith("paused") or lowered.startswith("off"):
            return "Paused"
        return "Ready"


def decode_photo_image(path: str, requested_size: QSize | None = None) -> PhotoLoadResult:
    started = time.perf_counter()
    target = Path(path)
    requested_size = requested_size or QSize()
    if not path or not target.exists():
        return _result(path, "file_missing", "File missing. Use Open Folder to inspect the source location.", str(target), started)
    suffix = target.suffix.casefold()
    if suffix not in SUPPORTED_IMAGE_SUFFIXES:
        return _result(path, "unsupported_format", f"Unsupported image format {suffix or '(none)'}. Use Open Externally or Open Folder.", str(target), started)

    reader = QImageReader(str(target))
    reader.setAutoTransform(True)
    if requested_size.isValid() and suffix not in {".heic", ".heif"}:
        reader.setScaledSize(_bounded_decode_size(reader.size(), requested_size))
    image = reader.read()
    if not image.isNull():
        return _image_result(path, image, started)

    if suffix in {".heic", ".heif"}:
        try:
            import pillow_heif  # type: ignore[import-not-found]

            pillow_heif.register_heif_opener()
        except ImportError as exc:
            LOGGER.warning("Atlas photo preview missing HEIC support for %s: %s", target, exc)
            return _result(path, "unsupported_format", "HEIC preview support is not installed. Use Open Externally or Open Folder.", str(exc), started)

    try:
        image = _load_qimage_with_pillow(target, requested_size)
        return _image_result(path, image, started)
    except ImportError as exc:
        LOGGER.warning("Atlas photo preview missing Pillow decoder for %s: %s", target, exc)
        return _result(path, "unsupported_format", "Image preview decoder is not installed. Use Open Externally or Open Folder.", str(exc), started)
    except Exception as exc:
        LOGGER.warning("Atlas photo preview decode failed for %s: %s", target, exc)
        return _result(path, "decode_failed", f"Decode failed for {target.name}. Use Open Externally or Open Folder.", repr(exc), started)


def _load_qimage_with_pillow(path: Path, requested_size: QSize) -> QImage:
    from PIL import Image, ImageOps

    with Image.open(path) as image:
        image = ImageOps.exif_transpose(image)
        image = image.convert("RGBA")
        max_width = requested_size.width() * 3 if requested_size.isValid() else 5000
        max_height = requested_size.height() * 3 if requested_size.isValid() else 5000
        image.thumbnail((max(900, min(5000, max_width)), max(700, min(5000, max_height))))
        width, height = image.size
        data = image.tobytes("raw", "RGBA")
    return QImage(data, width, height, width * 4, QImage.Format.Format_RGBA8888).copy()


def _bounded_decode_size(source_size: QSize, requested_size: QSize) -> QSize:
    if not source_size.isValid() or not requested_size.isValid():
        return QSize()
    bounds = QSize(max(480, requested_size.width() * 2), max(360, requested_size.height() * 2))
    scaled = QSize(source_size)
    scaled.scale(bounds, Qt.AspectRatioMode.KeepAspectRatio)
    return scaled


def _cache_key(path: Path, requested_size: QSize) -> tuple:
    bucket = _size_bucket(requested_size)
    return (_normal_path_key(path), bucket)


def _size_bucket(size: QSize) -> tuple[str, int]:
    if not size.isValid():
        return ("full", 0)
    if max(size.width(), size.height()) <= 260:
        return ("thumb", 0)
    return ("full", 0)


def _cache_key_is_thumbnail(cache_key: tuple) -> bool:
    return bool(cache_key and cache_key[-1][0] == "thumb")


def _cache_result_bytes(result: PhotoLoadResult) -> int:
    if result.image.isNull():
        return 0
    return max(0, int(result.image.sizeInBytes()))


def _image_result(path: str, image: QImage, started: float) -> PhotoLoadResult:
    return PhotoLoadResult(path=path, image=image, state="loaded", decode_ms=(time.perf_counter() - started) * 1000)


def _result(path: str, state: str, message: str, detail: str, started: float) -> PhotoLoadResult:
    return PhotoLoadResult(path=path, image=QImage(), state=state, message=message, detail=detail, decode_ms=(time.perf_counter() - started) * 1000)


def _copy_result(result: PhotoLoadResult, *, from_cache: bool) -> PhotoLoadResult:
    return PhotoLoadResult(
        path=result.path,
        image=result.image,
        state=result.state,
        message=result.message,
        detail=result.detail,
        decode_ms=result.decode_ms,
        from_cache=from_cache,
    )


def _priority_reason(priority: int) -> str:
    return {
        1: "Carousel preload: adjacent image",
        2: "Carousel preload: current EOAT photo set",
        3: "Idle preload: visible photo library",
        4: "Idle preload: nearby EOATs",
        5: "Idle preload: other EOAT photo sets",
    }.get(priority, "Photo load")


def _unique_photo_paths(records: Any) -> list[str]:
    paths: list[str] = []
    for record in records or ():
        if record is None:
            continue
        photo_set = getattr(record, "photos", None)
        if photo_set is None:
            continue
        for photo in (*getattr(photo_set, "photos", ()), *getattr(photo_set, "indexed_photos", ())):
            path = getattr(photo, "path", "")
            if path:
                paths.append(path)
    return _unique_existing_image_paths(paths)


def _unique_existing_image_paths(paths: Any) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in paths or ():
        text = str(raw or "").strip()
        if not text:
            continue
        target = Path(text)
        if target.suffix.casefold() not in SUPPORTED_IMAGE_SUFFIXES:
            continue
        key = _normal_path_key(target)
        if key in seen:
            continue
        seen.add(key)
        result.append(str(target))
    return result


def _normal_path_key(path: str | Path) -> str:
    text = os.path.normpath(str(path))
    return os.path.normcase(os.path.abspath(text))
