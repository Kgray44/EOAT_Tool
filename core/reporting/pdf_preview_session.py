from __future__ import annotations

import logging
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)

AUTO_SAVE_CLOSE_SECONDS = 10.0


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

    def __post_init__(self) -> None:
        self.temp_pdf_path = Path(self.temp_pdf_path)
        self.default_save_path = Path(self.default_save_path)
        if not self.opened_at:
            self.opened_at = time.monotonic()

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
                return "auto_save_failed"
            self.closed = True
            self.cleanup_temp_if_needed()
            return "auto_saved"
        self.closed = True
        self.cleanup_temp_if_needed()
        return "saved" if self.saved else "closed_without_saving"

    def cleanup_temp_if_needed(self) -> bool:
        if self.final_saved_path is not None and self.temp_pdf_path.resolve(strict=False) == self.final_saved_path.resolve(strict=False):
            return False
        try:
            if self.temp_pdf_path.exists():
                self.temp_pdf_path.unlink()
                return True
        except OSError:
            LOGGER.warning("Could not delete temporary PDF preview file: %s", self.temp_pdf_path, exc_info=True)
        return False


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


__all__ = ["AUTO_SAVE_CLOSE_SECONDS", "PdfPreviewSession"]
