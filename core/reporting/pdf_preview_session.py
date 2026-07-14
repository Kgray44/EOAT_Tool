from __future__ import annotations

import logging
import shutil
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)

AUTO_SAVE_CLOSE_SECONDS = 10.0
SETUP_PACKET_PREVIEW_DIRNAME = "eoat_atlas_setup_packet_previews"
DEFAULT_CLEANUP_RETRY_DELAYS = (0.1, 0.35, 1.0)
ABANDONED_PREVIEW_MIN_AGE_SECONDS = 60 * 60

_REGISTRY_LOCK = threading.RLock()
_ACTIVE_PREVIEW_PATHS: set[str] = set()
_PENDING_PREVIEW_PATHS: set[str] = set()


def setup_packet_preview_dir() -> Path:
    return Path(tempfile.gettempdir()) / SETUP_PACKET_PREVIEW_DIRNAME


def _path_key(path: Path) -> str:
    return str(path.resolve(strict=False)).casefold()


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
    except (OSError, ValueError):
        return False
    return True


def _default_retry_scheduler(delay_seconds: float, callback: Callable[[], None]) -> threading.Timer:
    timer = threading.Timer(max(0.0, delay_seconds), callback)
    timer.daemon = True
    timer.start()
    return timer


@dataclass
class PdfPreviewSession:
    record_type: str
    record_id: str
    temp_pdf_path: Path
    default_save_path: Path
    options: Any = None
    opened_at: float = 0.0
    saved: bool = False
    auto_saved: bool = False
    closed: bool = False
    final_saved_path: Path | None = None
    auto_save_close_seconds: float = AUTO_SAVE_CLOSE_SECONDS
    temp_preview_dir: Path | None = None
    cleanup_retry_delays: tuple[float, ...] = DEFAULT_CLEANUP_RETRY_DELAYS
    retry_scheduler: Callable[[float, Callable[[], None]], Any] = field(
        default=_default_retry_scheduler,
        repr=False,
        compare=False,
    )
    _cleanup_attempt: int = field(default=0, init=False, repr=False)
    _cleanup_retry_scheduled: bool = field(default=False, init=False, repr=False)
    _cleanup_warning_logged: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        self.temp_pdf_path = Path(self.temp_pdf_path)
        self.default_save_path = Path(self.default_save_path)
        if self.temp_preview_dir is not None:
            self.temp_preview_dir = Path(self.temp_preview_dir)
        if not self.opened_at:
            self.opened_at = time.monotonic()
        if self._cleanup_path_is_safe():
            with _REGISTRY_LOCK:
                _ACTIVE_PREVIEW_PATHS.add(_path_key(self.temp_pdf_path))

    @property
    def age_seconds(self) -> float:
        return max(0.0, time.monotonic() - self.opened_at)

    def should_auto_save_on_close(self) -> bool:
        return (
            not self.saved
            and not self.auto_saved
            and not self.closed
            and self.age_seconds < max(0.0, float(self.auto_save_close_seconds))
        )

    def save_as(self, target_path: str | Path | None = None, *, auto: bool = False) -> Path:
        target = Path(target_path) if target_path is not None else self.default_save_path
        if auto:
            target = _unique_path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        if self.temp_pdf_path.resolve(strict=False) != target.resolve(strict=False):
            shutil.copy2(self.temp_pdf_path, target)
        self.saved = True
        self.auto_saved = bool(auto)
        self.final_saved_path = target
        return target

    def close(self) -> str:
        if self.closed:
            return "already_closed"
        if self.should_auto_save_on_close():
            try:
                self.save_as(self.default_save_path, auto=True)
            except Exception:
                LOGGER.exception("Could not auto-save PDF preview %s", self.temp_pdf_path)
                self.closed = True
                self._mark_inactive()
                return "auto_save_failed"
            self.closed = True
            self._mark_inactive()
            self.cleanup_temp_if_needed()
            return "auto_saved"
        self.closed = True
        self._mark_inactive()
        self.cleanup_temp_if_needed()
        return "saved" if self.saved else "closed_without_saving"

    def cleanup_temp_if_needed(self) -> bool:
        if self.final_saved_path is not None and self.temp_pdf_path.resolve(strict=False) == self.final_saved_path.resolve(strict=False):
            self._clear_pending()
            return False
        if not self._cleanup_path_is_safe():
            LOGGER.debug("Refusing to clean PDF outside its registered preview directory: %s", self.temp_pdf_path)
            return False
        self._cleanup_retry_scheduled = False
        try:
            self.temp_pdf_path.unlink(missing_ok=True)
        except OSError as exc:
            self._cleanup_attempt += 1
            self._mark_pending()
            if self._cleanup_attempt <= len(self.cleanup_retry_delays):
                delay = self.cleanup_retry_delays[self._cleanup_attempt - 1]
                self._cleanup_retry_scheduled = True
                self.retry_scheduler(delay, self.cleanup_temp_if_needed)
            elif not self._cleanup_warning_logged:
                self._cleanup_warning_logged = True
                LOGGER.warning("Temporary PDF preview remains locked; cleanup deferred: %s (%s)", self.temp_pdf_path, exc)
            return False
        self._mark_inactive()
        self._clear_pending()
        return True

    def defer_cleanup(self) -> None:
        """Leave a preview for an external viewer and make it maintenance-eligible."""
        self.closed = True
        self._mark_inactive()
        self._mark_pending()

    def _cleanup_path_is_safe(self) -> bool:
        return self.temp_preview_dir is not None and _is_within(self.temp_pdf_path, self.temp_preview_dir)

    def _mark_inactive(self) -> None:
        with _REGISTRY_LOCK:
            _ACTIVE_PREVIEW_PATHS.discard(_path_key(self.temp_pdf_path))

    def _mark_pending(self) -> None:
        with _REGISTRY_LOCK:
            _PENDING_PREVIEW_PATHS.add(_path_key(self.temp_pdf_path))

    def _clear_pending(self) -> None:
        with _REGISTRY_LOCK:
            _PENDING_PREVIEW_PATHS.discard(_path_key(self.temp_pdf_path))


def cleanup_abandoned_preview_files(
    preview_dir: str | Path | None = None,
    *,
    minimum_age_seconds: float = ABANDONED_PREVIEW_MIN_AGE_SECONDS,
    now: float | None = None,
) -> tuple[Path, ...]:
    """Best-effort maintenance for inactive previews left by earlier sessions."""
    root = Path(preview_dir) if preview_dir is not None else setup_packet_preview_dir()
    if not root.exists() or not root.is_dir():
        return ()
    current_time = time.time() if now is None else float(now)
    removed: list[Path] = []
    try:
        candidates = tuple(root.glob("*.pdf"))
    except OSError:
        LOGGER.debug("Could not enumerate PDF preview cleanup directory: %s", root, exc_info=True)
        return ()
    for path in candidates:
        if not _is_within(path, root):
            continue
        key = _path_key(path)
        with _REGISTRY_LOCK:
            if key in _ACTIVE_PREVIEW_PATHS:
                continue
        try:
            age = current_time - path.stat().st_mtime
            if age < max(0.0, minimum_age_seconds):
                continue
            path.unlink(missing_ok=True)
        except OSError:
            # A viewer from this or a previous session may still own the file.
            # The next maintenance pass will retry without flooding the log.
            continue
        with _REGISTRY_LOCK:
            _PENDING_PREVIEW_PATHS.discard(key)
        removed.append(path)
    return tuple(removed)


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    for index in range(2, 1000):
        candidate = path.with_name(f"{stem}_{index}{suffix}")
        if not candidate.exists():
            return candidate
    return path.with_name(f"{stem}_{int(time.time())}{suffix}")


__all__ = [
    "ABANDONED_PREVIEW_MIN_AGE_SECONDS",
    "AUTO_SAVE_CLOSE_SECONDS",
    "PdfPreviewSession",
    "cleanup_abandoned_preview_files",
    "setup_packet_preview_dir",
]
