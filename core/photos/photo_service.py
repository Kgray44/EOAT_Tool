from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QRunnable, QSize, Qt, QThreadPool, QTimer, Signal, Slot
from PySide6.QtGui import QImage, QImageReader, QImageWriter

from core.performance import log_perf_marker, perf_timer
from core.safe_files import ensure_directory

LOGGER = logging.getLogger(__name__)

SUPPORTED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".heic", ".heif"}
DEFAULT_MEMORY_BUDGET_BYTES = 2 * 1024 * 1024 * 1024
DEFAULT_THUMBNAIL_BUDGET_BYTES = 512 * 1024 * 1024
DEFAULT_FULL_IMAGE_BUDGET_BYTES = DEFAULT_MEMORY_BUDGET_BYTES - DEFAULT_THUMBNAIL_BUDGET_BYTES


@dataclass(frozen=True)
class _PhotoRequest:
    request_type: str
    photo_id: str
    path_candidates: tuple[str, ...]
    size: QSize
    priority: int
    context_id: str
    project_root: str
    cache_dir: Path
    disk_format: str
    disk_suffix: str
    generation: int


@dataclass(frozen=True)
class _PhotoTaskResult:
    request_type: str
    photo_id: str
    context_id: str
    image: QImage
    resolved_path: str = ""
    cache_key: str = ""
    state: str = "loaded"
    reason: str = ""
    from_disk: bool = False
    cancelled: bool = False
    cost_bytes: int = 0
    requested_size: tuple[int, int] = (0, 0)
    generation: int = 0


@dataclass(frozen=True)
class _ImageCacheEntry:
    image: QImage
    resolved_path: str
    cost_bytes: int
    kind: str


class _PhotoWorkerSignals(QObject):
    finished = Signal(object)


class _PhotoTask(QRunnable):
    def __init__(self, request: _PhotoRequest, is_cancelled: Callable[[str, int], bool]):
        super().__init__()
        self.request = request
        self.is_cancelled = is_cancelled
        self.signals = _PhotoWorkerSignals()

    @Slot()
    def run(self) -> None:
        try:
            result = _run_photo_request(self.request, self.is_cancelled)
        except Exception as exc:  # pragma: no cover - defensive worker guard
            LOGGER.exception("PhotoService worker failed for %s", self.request.photo_id)
            result = _PhotoTaskResult(
                request_type=self.request.request_type,
                photo_id=self.request.photo_id,
                context_id=self.request.context_id,
                image=QImage(),
                state="error",
                reason=f"{type(exc).__name__}: {exc}",
                generation=self.request.generation,
            )
        try:
            self.signals.finished.emit(result)
        except RuntimeError:
            LOGGER.debug("PhotoService result dropped because signal receiver was deleted for %s", self.request.photo_id)


class PhotoService(QObject):
    thumbnail_ready = Signal(str, object, str, str)
    full_image_ready = Signal(str, object, str, str)
    photo_load_failed = Signal(str, str, str)

    def __init__(
        self,
        project_root: str | Path,
        parent: QObject | None = None,
        *,
        memory_budget_bytes: int = DEFAULT_MEMORY_BUDGET_BYTES,
        thumbnail_budget_bytes: int = DEFAULT_THUMBNAIL_BUDGET_BYTES,
        max_workers: int = 3,
    ):
        super().__init__(parent)
        self.project_root = str(project_root or "")
        self.cache_dir = _thumbnail_cache_dir(self.project_root)
        self.memory_budget_bytes = max(32 * 1024 * 1024, int(memory_budget_bytes or DEFAULT_MEMORY_BUDGET_BYTES))
        self.thumbnail_budget_bytes = max(16 * 1024 * 1024, min(int(thumbnail_budget_bytes), self.memory_budget_bytes))
        self.full_image_budget_bytes = max(16 * 1024 * 1024, self.memory_budget_bytes - self.thumbnail_budget_bytes)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(max(1, min(4, int(max_workers or 3))))
        self._cache: OrderedDict[str, _ImageCacheEntry] = OrderedDict()
        self._latest_thumbnail_key: dict[tuple[str, tuple[int, int]], str] = {}
        self._latest_full_key: dict[str, str] = {}
        self._cache_bytes = 0
        self._cache_bytes_by_kind = {"thumbnail": 0, "full": 0}
        self._context_generation: dict[str, int] = {}
        self._running_tasks: set[_PhotoTask] = set()
        self._paused_requests: list[_PhotoRequest] = []
        self._prefetch_paused = False
        self._lock = threading.RLock()
        self._disk_format, self._disk_suffix = _preferred_disk_thumbnail_format()

    def set_project_root(self, project_root: str | Path) -> None:
        self.project_root = str(project_root or "")
        self.cache_dir = _thumbnail_cache_dir(self.project_root)

    def request_thumbnail(
        self,
        photo_id: str,
        path_candidates: list[str],
        size: tuple[int, int],
        priority: int,
        context_id: str,
    ) -> None:
        normalized_size = _qsize(size)
        normalized_photo_id = str(photo_id or "").strip() or _fallback_photo_id(path_candidates)
        normalized_context = str(context_id or "photo:default")
        with perf_timer(
            self.project_root,
            "photo_service.request_thumbnail",
            details={
                "photo_id": normalized_photo_id,
                "context_id": normalized_context,
                "priority": priority,
                "candidate_count": len(path_candidates or ()),
                "width": normalized_size.width(),
                "height": normalized_size.height(),
            },
            source="photo_service",
            page_tool="photos",
        ):
            generation = self._context_generation_for(normalized_context)
            cached = self.get_cached_thumbnail(normalized_photo_id, (normalized_size.width(), normalized_size.height()))
            if cached is not None:
                self._emit_thumbnail_memory_hit(normalized_photo_id, cached, normalized_context)
                return
            request = _PhotoRequest(
                request_type="thumbnail",
                photo_id=normalized_photo_id,
                path_candidates=tuple(str(path or "") for path in path_candidates or () if str(path or "").strip()),
                size=normalized_size,
                priority=int(priority or 0),
                context_id=normalized_context,
                project_root=self.project_root,
                cache_dir=self.cache_dir,
                disk_format=self._disk_format,
                disk_suffix=self._disk_suffix,
                generation=generation,
            )
            self._start_or_pause(request)

    def request_full_image(
        self,
        photo_id: str,
        path_candidates: list[str],
        priority: int,
        context_id: str,
    ) -> None:
        normalized_photo_id = str(photo_id or "").strip() or _fallback_photo_id(path_candidates)
        normalized_context = str(context_id or "lightbox:default")
        with perf_timer(
            self.project_root,
            "lightbox.request_full_image",
            details={
                "photo_id": normalized_photo_id,
                "context_id": normalized_context,
                "priority": priority,
                "candidate_count": len(path_candidates or ()),
            },
            source="photo_service",
            page_tool="photos",
        ):
            generation = self._context_generation_for(normalized_context)
            cached = self.get_cached_full_image(normalized_photo_id)
            if cached is not None:
                log_perf_marker(
                    self.project_root,
                    "photo_service.memory_cache_hit",
                    details={"photo_id": normalized_photo_id, "context_id": normalized_context, "kind": "full"},
                    source="photo_service",
                    page_tool="photos",
                )
                self._emit_full_image_ready(normalized_photo_id, cached, "", normalized_context)
                return
            request = _PhotoRequest(
                request_type="full",
                photo_id=normalized_photo_id,
                path_candidates=tuple(str(path or "") for path in path_candidates or () if str(path or "").strip()),
                size=QSize(),
                priority=int(priority or 100),
                context_id=normalized_context,
                project_root=self.project_root,
                cache_dir=self.cache_dir,
                disk_format=self._disk_format,
                disk_suffix=self._disk_suffix,
                generation=generation,
            )
            self._start_or_pause(request)

    def cancel_context(self, context_id: str) -> None:
        normalized = str(context_id or "").strip()
        if not normalized:
            return
        with self._lock:
            self._context_generation[normalized] = self._context_generation.get(normalized, 0) + 1
            self._paused_requests = [request for request in self._paused_requests if request.context_id != normalized]

    def shutdown(self, wait_ms: int = 0) -> None:
        with self._lock:
            contexts = set(self._context_generation)
            contexts.update(request.context_id for request in self._paused_requests)
            contexts.update(task.request.context_id for task in self._running_tasks)
            for context in contexts:
                self._context_generation[context] = self._context_generation.get(context, 0) + 1
            self._paused_requests.clear()
        try:
            self.pool.clear()
            wait = max(0, int(wait_ms))
            if wait:
                self.pool.waitForDone(wait)
        except RuntimeError:
            return

    def pause_prefetch(self) -> None:
        with self._lock:
            self._prefetch_paused = True

    def resume_prefetch(self) -> None:
        with self._lock:
            self._prefetch_paused = False
            requests = list(self._paused_requests)
            self._paused_requests.clear()
        for request in sorted(requests, key=lambda item: item.priority, reverse=True):
            self._start_task(request)

    def get_cached_thumbnail(self, photo_id: str, size: tuple[int, int]):
        key = self._latest_thumbnail_key.get((str(photo_id or ""), (int(size[0]), int(size[1]))))
        if not key:
            return None
        entry = self._get_cache_entry(key)
        return entry.image.copy() if entry is not None else None

    def get_cached_full_image(self, photo_id: str):
        key = self._latest_full_key.get(str(photo_id or ""))
        if not key:
            return None
        entry = self._get_cache_entry(key)
        return entry.image.copy() if entry is not None else None

    def stats(self) -> dict[str, object]:
        with self._lock:
            return {
                "memory_budget_mb": round(self.memory_budget_bytes / (1024 * 1024), 1),
                "thumbnail_budget_mb": round(self.thumbnail_budget_bytes / (1024 * 1024), 1),
                "full_image_budget_mb": round(self.full_image_budget_bytes / (1024 * 1024), 1),
                "memory_used_mb": round(self._cache_bytes / (1024 * 1024), 1),
                "thumbnail_used_mb": round(self._cache_bytes_by_kind["thumbnail"] / (1024 * 1024), 1),
                "full_used_mb": round(self._cache_bytes_by_kind["full"] / (1024 * 1024), 1),
                "cache_entries": len(self._cache),
                "running_tasks": len(self._running_tasks),
                "paused_requests": len(self._paused_requests),
                "worker_limit": self.pool.maxThreadCount(),
                "disk_cache_dir": str(self.cache_dir),
                "disk_format": self._disk_format,
            }

    def _start_or_pause(self, request: _PhotoRequest) -> None:
        with self._lock:
            if self._prefetch_paused and request.priority < 60:
                self._paused_requests.append(request)
                return
        self._start_task(request)

    def _start_task(self, request: _PhotoRequest) -> None:
        task = _PhotoTask(request, self._is_context_cancelled)
        task.signals.finished.connect(self._task_finished)
        with self._lock:
            self._running_tasks.add(task)
        self.pool.start(task, request.priority)

    def _context_generation_for(self, context_id: str) -> int:
        with self._lock:
            return self._context_generation.get(str(context_id or ""), 0)

    def _is_context_cancelled(self, context_id: str, generation: int) -> bool:
        with self._lock:
            return self._context_generation.get(str(context_id or ""), 0) != int(generation)

    def _get_cache_entry(self, key: str) -> _ImageCacheEntry | None:
        with self._lock:
            entry = self._cache.get(key)
            if entry is not None:
                self._cache.move_to_end(key)
            return entry

    def _emit_thumbnail_memory_hit(self, photo_id: str, image: QImage, context_id: str) -> None:
        log_perf_marker(
            self.project_root,
            "photo_service.memory_cache_hit",
            details={"photo_id": photo_id, "context_id": context_id, "kind": "thumbnail"},
            source="photo_service",
            page_tool="photos",
        )
        QTimer.singleShot(0, lambda: self._emit_thumbnail_ready(photo_id, image, "", context_id))

    def _emit_thumbnail_ready(self, photo_id: str, image: QImage, resolved_path: str, context_id: str) -> None:
        log_perf_marker(
            self.project_root,
            "photo_service.thumbnail_ready_to_ui",
            details={"photo_id": photo_id, "context_id": context_id, "path": resolved_path},
            source="photo_service",
            page_tool="photos",
        )
        self.thumbnail_ready.emit(photo_id, image, resolved_path, context_id)

    def _emit_full_image_ready(self, photo_id: str, image: QImage, resolved_path: str, context_id: str) -> None:
        log_perf_marker(
            self.project_root,
            "lightbox.full_image_ready_to_ui",
            details={"photo_id": photo_id, "context_id": context_id, "path": resolved_path},
            source="photo_service",
            page_tool="photos",
        )
        self.full_image_ready.emit(photo_id, image, resolved_path, context_id)

    @Slot(object)
    def _task_finished(self, result: _PhotoTaskResult) -> None:
        sender = self.sender()
        with self._lock:
            task = next((item for item in self._running_tasks if item.signals is sender), None)
            if task is not None:
                self._running_tasks.discard(task)
        if result.cancelled or self._is_context_cancelled(result.context_id, result.generation):
            return
        if result.state != "loaded" or result.image.isNull():
            self.photo_load_failed.emit(result.photo_id, result.reason or result.state, result.context_id)
            return
        self._store_memory_result(result)
        if result.request_type == "thumbnail":
            self._emit_thumbnail_ready(result.photo_id, result.image, result.resolved_path, result.context_id)
        else:
            self._emit_full_image_ready(result.photo_id, result.image, result.resolved_path, result.context_id)

    def _store_memory_result(self, result: _PhotoTaskResult) -> None:
        if not result.cache_key:
            return
        kind = "thumbnail" if result.request_type == "thumbnail" else "full"
        entry = _ImageCacheEntry(
            image=result.image.copy(),
            resolved_path=result.resolved_path,
            cost_bytes=max(0, int(result.cost_bytes or result.image.sizeInBytes())),
            kind=kind,
        )
        with self._lock:
            previous = self._cache.pop(result.cache_key, None)
            if previous is not None:
                self._cache_bytes -= previous.cost_bytes
                self._cache_bytes_by_kind[previous.kind] -= previous.cost_bytes
            self._cache[result.cache_key] = entry
            self._cache_bytes += entry.cost_bytes
            self._cache_bytes_by_kind[kind] += entry.cost_bytes
            if kind == "thumbnail":
                size = (result.image.width(), result.image.height())
                self._latest_thumbnail_key[(result.photo_id, size)] = result.cache_key
                requested = result.requested_size
                if requested != size:
                    self._latest_thumbnail_key[(result.photo_id, requested)] = result.cache_key
            else:
                self._latest_full_key[result.photo_id] = result.cache_key
            self._evict_to_budget_locked()

    def _evict_to_budget_locked(self) -> None:
        self._evict_kind_to_budget_locked("thumbnail", self.thumbnail_budget_bytes)
        self._evict_kind_to_budget_locked("full", self.full_image_budget_bytes)
        while self._cache and self._cache_bytes > self.memory_budget_bytes:
            self._evict_key_locked(next(iter(self._cache)))

    def _evict_kind_to_budget_locked(self, kind: str, budget: int) -> None:
        while self._cache_bytes_by_kind.get(kind, 0) > budget:
            key = next((cache_key for cache_key, entry in self._cache.items() if entry.kind == kind), "")
            if not key:
                return
            self._evict_key_locked(key)

    def _evict_key_locked(self, key: str) -> None:
        entry = self._cache.pop(key, None)
        if entry is None:
            return
        self._cache_bytes -= entry.cost_bytes
        self._cache_bytes_by_kind[entry.kind] -= entry.cost_bytes
        for mapping_key, cache_key in list(self._latest_thumbnail_key.items()):
            if cache_key == key:
                self._latest_thumbnail_key.pop(mapping_key, None)
        for mapping_key, cache_key in list(self._latest_full_key.items()):
            if cache_key == key:
                self._latest_full_key.pop(mapping_key, None)


def _run_photo_request(request: _PhotoRequest, is_cancelled: Callable[[str, int], bool]) -> _PhotoTaskResult:
    if is_cancelled(request.context_id, request.generation):
        return _cancelled_result(request)
    resolved = _resolve_first_existing_path(request, is_cancelled)
    if resolved is None:
        return _PhotoTaskResult(
            request_type=request.request_type,
            photo_id=request.photo_id,
            context_id=request.context_id,
            image=QImage(),
            state="missing",
            reason="No valid photo path candidate exists.",
            generation=request.generation,
        )
    if is_cancelled(request.context_id, request.generation):
        return _cancelled_result(request, resolved)
    stat = _safe_stat(resolved)
    if stat is None:
        return _PhotoTaskResult(
            request_type=request.request_type,
            photo_id=request.photo_id,
            context_id=request.context_id,
            image=QImage(),
            resolved_path=str(resolved),
            state="missing",
            reason="Photo file disappeared before decode.",
            generation=request.generation,
        )
    if request.request_type == "thumbnail":
        return _thumbnail_request_result(request, resolved, stat, is_cancelled)
    return _full_image_request_result(request, resolved, stat, is_cancelled)


def _thumbnail_request_result(
    request: _PhotoRequest,
    resolved: Path,
    stat: os.stat_result,
    is_cancelled: Callable[[str, int], bool],
) -> _PhotoTaskResult:
    cache_key = _memory_cache_key("thumbnail", request.photo_id, resolved, stat, request.size)
    disk_path = _disk_thumbnail_path(request, resolved, stat)
    if disk_path.exists():
        with perf_timer(
            request.project_root,
            "photo_service.disk_cache_hit",
            details={"photo_id": request.photo_id, "context_id": request.context_id, "path": str(disk_path)},
            source="photo_service",
            page_tool="photos",
        ):
            image = _read_image(disk_path, QSize(), request, is_cancelled, operation="photo_service.image_decode_worker")
        if is_cancelled(request.context_id, request.generation):
            return _cancelled_result(request, resolved)
        if not image.isNull():
            return _PhotoTaskResult(
                request_type=request.request_type,
                photo_id=request.photo_id,
                context_id=request.context_id,
                image=image,
                resolved_path=str(resolved),
                cache_key=cache_key,
                from_disk=True,
                cost_bytes=int(image.sizeInBytes()),
                requested_size=(request.size.width(), request.size.height()),
                generation=request.generation,
            )
    image = _read_image(resolved, request.size, request, is_cancelled, operation="photo_service.image_decode_worker")
    if is_cancelled(request.context_id, request.generation):
        return _cancelled_result(request, resolved)
    if image.isNull():
        return _PhotoTaskResult(
            request_type=request.request_type,
            photo_id=request.photo_id,
            context_id=request.context_id,
            image=QImage(),
            resolved_path=str(resolved),
            state="decode_failed",
            reason=f"Could not decode {resolved.name}.",
            generation=request.generation,
        )
    with perf_timer(
        request.project_root,
        "photo_service.thumbnail_scale_worker",
        details={
            "photo_id": request.photo_id,
            "context_id": request.context_id,
            "path": str(resolved),
            "width": request.size.width(),
            "height": request.size.height(),
        },
        source="photo_service",
        page_tool="photos",
    ):
        thumbnail = image.scaled(
            request.size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    if is_cancelled(request.context_id, request.generation):
        return _cancelled_result(request, resolved)
    _save_disk_thumbnail(request, disk_path, thumbnail)
    return _PhotoTaskResult(
        request_type=request.request_type,
        photo_id=request.photo_id,
        context_id=request.context_id,
        image=thumbnail,
        resolved_path=str(resolved),
        cache_key=cache_key,
        cost_bytes=int(thumbnail.sizeInBytes()),
        requested_size=(request.size.width(), request.size.height()),
        generation=request.generation,
    )


def _full_image_request_result(
    request: _PhotoRequest,
    resolved: Path,
    stat: os.stat_result,
    is_cancelled: Callable[[str, int], bool],
) -> _PhotoTaskResult:
    cache_key = _memory_cache_key("full", request.photo_id, resolved, stat, QSize())
    image = _read_image(resolved, QSize(), request, is_cancelled, operation="lightbox.full_image_decode_worker")
    if is_cancelled(request.context_id, request.generation):
        return _cancelled_result(request, resolved)
    if image.isNull():
        return _PhotoTaskResult(
            request_type=request.request_type,
            photo_id=request.photo_id,
            context_id=request.context_id,
            image=QImage(),
            resolved_path=str(resolved),
            state="decode_failed",
            reason=f"Could not decode {resolved.name}.",
            generation=request.generation,
        )
    return _PhotoTaskResult(
        request_type=request.request_type,
        photo_id=request.photo_id,
        context_id=request.context_id,
        image=image,
        resolved_path=str(resolved),
        cache_key=cache_key,
        cost_bytes=int(image.sizeInBytes()),
        generation=request.generation,
    )


def _resolve_first_existing_path(request: _PhotoRequest, is_cancelled: Callable[[str, int], bool]) -> Path | None:
    with perf_timer(
        request.project_root,
        "photo_service.path_resolution_worker",
        details={
            "ui_sensitive": "photo_path_resolution",
            "photo_id": request.photo_id,
            "context_id": request.context_id,
            "candidate_count": len(request.path_candidates),
        },
        source="photo_service",
        page_tool="photos",
    ):
        for candidate in request.path_candidates:
            if is_cancelled(request.context_id, request.generation):
                return None
            path = _normalize_candidate(candidate, request.project_root)
            if not path:
                continue
            try:
                if path.exists() and path.is_file():
                    return path
            except OSError:
                LOGGER.debug("Photo path candidate could not be checked: %s", path)
                continue
    return None


def _read_image(
    path: Path,
    requested_size: QSize,
    request: _PhotoRequest,
    is_cancelled: Callable[[str, int], bool],
    *,
    operation: str,
) -> QImage:
    with perf_timer(
        request.project_root,
        operation,
        details={
            "ui_sensitive": "thumbnail_decode" if operation == "photo_service.image_decode_worker" else "image_decode",
            "photo_id": request.photo_id,
            "context_id": request.context_id,
            "path": str(path),
            "requested_width": requested_size.width(),
            "requested_height": requested_size.height(),
            "loader": "QImageReader",
        },
        source="photo_service",
        page_tool="photos",
    ):
        if is_cancelled(request.context_id, request.generation):
            return QImage()
        if path.suffix.casefold() not in SUPPORTED_IMAGE_SUFFIXES:
            return QImage()
        reader = QImageReader(str(path))
        reader.setAutoTransform(True)
        if requested_size.isValid() and path.suffix.casefold() not in {".heic", ".heif"}:
            reader.setScaledSize(_bounded_decode_size(reader.size(), requested_size))
        image = reader.read()
        if not image.isNull():
            return image
        if path.suffix.casefold() in {".heic", ".heif"}:
            try:
                return _load_qimage_with_pillow(path, requested_size)
            except Exception as exc:
                LOGGER.debug("HEIC fallback decode failed for %s: %s", path, exc)
        return QImage()


def _save_disk_thumbnail(request: _PhotoRequest, disk_path: Path, image: QImage) -> None:
    with perf_timer(
        request.project_root,
        "photo_service.disk_thumbnail_save",
        details={"photo_id": request.photo_id, "context_id": request.context_id, "path": str(disk_path)},
        source="photo_service",
        page_tool="photos",
    ):
        try:
            ensure_directory(disk_path.parent)
            temp_path = disk_path.with_suffix(f".tmp{disk_path.suffix}")
            if not image.save(str(temp_path), request.disk_format, 84):
                LOGGER.warning("Could not save photo thumbnail cache file: %s", disk_path)
                return
            Path(temp_path).replace(disk_path)
        except OSError as exc:
            LOGGER.warning("Photo thumbnail cache write failed for %s: %s", disk_path, exc)


def _load_qimage_with_pillow(path: Path, requested_size: QSize) -> QImage:
    if path.suffix.casefold() in {".heic", ".heif"}:
        import pillow_heif  # type: ignore[import-not-found]

        pillow_heif.register_heif_opener()
    from PIL import Image, ImageOps

    with Image.open(path) as image:
        image = ImageOps.exif_transpose(image)
        image = image.convert("RGBA")
        if requested_size.isValid():
            max_width = max(900, min(5000, requested_size.width() * 3))
            max_height = max(700, min(5000, requested_size.height() * 3))
            image.thumbnail((max_width, max_height))
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


def _normalize_candidate(candidate: str, project_root: str) -> Path | None:
    text = str(candidate or "").strip()
    if not text:
        return None
    path = Path(text)
    if path.is_absolute():
        return path
    root = Path(project_root) if str(project_root or "").strip() else Path.cwd()
    return root / path


def _safe_stat(path: Path):
    try:
        return path.stat()
    except OSError:
        return None


def _qsize(size: tuple[int, int]) -> QSize:
    width = max(1, int(size[0] if len(size) > 0 else 256))
    height = max(1, int(size[1] if len(size) > 1 else width))
    return QSize(width, height)


def _fallback_photo_id(path_candidates: list[str] | tuple[str, ...]) -> str:
    first = next((str(path) for path in path_candidates or () if str(path or "").strip()), "")
    return hashlib.sha1(first.encode("utf-8", errors="replace")).hexdigest()[:16] if first else "photo"


def _thumbnail_cache_dir(project_root: str | Path) -> Path:
    root = Path(project_root) if str(project_root or "").strip() else Path.cwd()
    return root / "00_Project_Admin" / "cache" / "photo_thumbnails"


def _preferred_disk_thumbnail_format() -> tuple[str, str]:
    formats = {bytes(item).decode("ascii", errors="ignore").casefold() for item in QImageWriter.supportedImageFormats()}
    if "webp" in formats:
        return "WEBP", ".webp"
    if "jpg" in formats or "jpeg" in formats:
        return "JPG", ".jpg"
    return "PNG", ".png"


def _memory_cache_key(kind: str, photo_id: str, path: Path, stat: os.stat_result, size: QSize) -> str:
    payload = "\0".join(
        (
            kind,
            str(photo_id or ""),
            _absolute_path_text(path),
            str(int(stat.st_mtime_ns)),
            str(int(stat.st_size)),
            str(size.width() if size.isValid() else 0),
            str(size.height() if size.isValid() else 0),
        )
    )
    return hashlib.sha256(payload.encode("utf-8", errors="replace")).hexdigest()


def _disk_thumbnail_path(request: _PhotoRequest, path: Path, stat: os.stat_result) -> Path:
    payload = "\0".join(
        (
            _absolute_path_text(path),
            str(int(stat.st_mtime_ns)),
            str(int(stat.st_size)),
            str(request.size.width()),
            str(request.size.height()),
        )
    )
    digest = hashlib.sha256(payload.encode("utf-8", errors="replace")).hexdigest()[:32]
    return request.cache_dir / f"{digest}_{request.size.width()}x{request.size.height()}{request.disk_suffix}"


def _absolute_path_text(path: Path) -> str:
    try:
        return os.path.abspath(path)
    except OSError:
        return str(path.absolute())


def _cancelled_result(request: _PhotoRequest, resolved: Path | None = None) -> _PhotoTaskResult:
    return _PhotoTaskResult(
        request_type=request.request_type,
        photo_id=request.photo_id,
        context_id=request.context_id,
        image=QImage(),
        resolved_path=str(resolved or ""),
        state="cancelled",
        cancelled=True,
        generation=request.generation,
    )


__all__ = ["PhotoService"]
