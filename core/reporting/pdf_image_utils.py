from __future__ import annotations

import hashlib
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.performance import log_perf_marker, perf_timer

LOGGER = logging.getLogger(__name__)

PDF_SAFE_FORMATS = {"JPEG", "PNG"}
PDF_SAFE_EXTENSIONS = {".jpg", ".jpeg", ".png"}
_FAILED_IMAGE_PREP: dict[str, PdfImageResult] = {}
_HEIF_REGISTERED: bool | None = None


@dataclass(frozen=True)
class PdfImageResult:
    ok: bool
    pdf_safe_path: str | None = None
    original_path: str | None = None
    reason: str | None = None
    converted: bool = False
    skipped: bool = False
    cache_hit: bool = False


def prepare_image_for_pdf(
    image_path: str | Path,
    project_root: Path,
    max_size: tuple[int, int] = (1200, 900),
    prefer_format: str = "JPEG",
) -> PdfImageResult:
    source = Path(str(image_path))
    root = Path(project_root) if project_root else Path.cwd()
    target_format = _normalized_format(prefer_format)
    max_size = _normalized_size(max_size)
    details = {
        "path": str(source),
        "requested_size": list(max_size),
        "target_format": target_format,
    }
    with perf_timer(root, "pdf.image_prepare", details=details, source="pdf_image_utils", page_tool="library_record"):
        try:
            stat = source.stat()
        except OSError as exc:
            return _skip(root, source, f"source file unavailable: {exc}")
        if stat.st_size <= 0:
            return _skip(root, source, "source file is empty")

        cache_key = _cache_key(source, stat.st_mtime_ns, stat.st_size, max_size, target_format)
        if cache_key in _FAILED_IMAGE_PREP:
            return _FAILED_IMAGE_PREP[cache_key]
        cache_dir = root / "00_Project_Admin" / "cache" / "pdf_images"
        suffix = ".jpg" if target_format == "JPEG" else ".png"
        target = cache_dir / f"{cache_key[:20]}_{max_size[0]}x{max_size[1]}{suffix}"
        if target.exists() and target.stat().st_size > 0:
            log_perf_marker(
                root,
                "pdf.image_cache_hit",
                details={**details, "cache_path": str(target), "source_mtime_ns": stat.st_mtime_ns},
                source="pdf_image_utils",
                page_tool="library_record",
            )
            return PdfImageResult(
                ok=True,
                pdf_safe_path=str(target),
                original_path=str(source),
                converted=True,
                cache_hit=True,
            )

        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return _remember_skip(root, cache_key, source, f"could not create PDF image cache: {exc}")

        qt_result = _convert_with_qt(source, target, root, max_size, target_format)
        if qt_result.ok:
            return qt_result
        pillow_result = _convert_with_pillow(source, target, root, max_size, target_format, qt_result.reason)
        if pillow_result.ok:
            return pillow_result
        return _remember_skip(
            root,
            cache_key,
            source,
            pillow_result.reason or qt_result.reason or "unsupported image format or decode failed",
        )


def prepare_images_for_pdf(
    photo_records: Iterable[Any],
    project_root: Path,
    max_size: tuple[int, int] = (1200, 900),
) -> list[PdfImageResult]:
    results: list[PdfImageResult] = []
    for photo in photo_records:
        raw_path = getattr(photo, "path", "") or ""
        results.append(prepare_image_for_pdf(raw_path, project_root, max_size=max_size))
    return results


def _normalized_format(value: str) -> str:
    text = str(value or "JPEG").strip().upper()
    return text if text in PDF_SAFE_FORMATS else "JPEG"


def _normalized_size(value: tuple[int, int]) -> tuple[int, int]:
    try:
        width, height = int(value[0]), int(value[1])
    except Exception:
        return (1200, 900)
    return (max(1, width), max(1, height))


def _cache_key(source: Path, mtime_ns: int, size: int, max_size: tuple[int, int], target_format: str) -> str:
    try:
        source_text = str(source.absolute())
    except OSError:
        source_text = str(source)
    payload = "|".join((source_text, str(mtime_ns), str(size), f"{max_size[0]}x{max_size[1]}", target_format))
    return hashlib.sha1(payload.encode("utf-8", errors="replace")).hexdigest()


def _convert_with_qt(source: Path, target: Path, root: Path, max_size: tuple[int, int], target_format: str) -> PdfImageResult:
    details = {"path": str(source), "cache_path": str(target), "requested_size": list(max_size), "target_format": target_format}
    with perf_timer(root, "pdf.image_convert_qt", details=details, source="pdf_image_utils", page_tool="library_record"):
        try:
            from PySide6.QtCore import Qt
            from PySide6.QtGui import QColor, QImage, QImageReader, QPainter

            reader = QImageReader(str(source))
            reader.setAutoTransform(True)
            image = reader.read()
            if image.isNull():
                reason = reader.errorString() or "Qt could not decode image"
                return PdfImageResult(ok=False, original_path=str(source), reason=reason, skipped=True)
            image = image.scaled(max_size[0], max_size[1], Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            if target_format == "JPEG":
                image = _qimage_for_jpeg(image, QImage, QPainter, QColor)
            if not image.save(str(target), target_format):
                return PdfImageResult(ok=False, original_path=str(source), reason=f"Qt could not save {target_format}", skipped=True)
            return PdfImageResult(ok=True, pdf_safe_path=str(target), original_path=str(source), converted=True)
        except Exception as exc:
            LOGGER.debug("Qt PDF image conversion failed for %s: %s", source, exc)
            return PdfImageResult(ok=False, original_path=str(source), reason=f"Qt conversion failed: {exc}", skipped=True)


def _qimage_for_jpeg(image, QImage, QPainter, QColor):
    if not image.hasAlphaChannel():
        return image.convertToFormat(QImage.Format.Format_RGB888)
    canvas = QImage(image.size(), QImage.Format.Format_RGB888)
    canvas.fill(QColor("white"))
    painter = QPainter(canvas)
    painter.drawImage(0, 0, image)
    painter.end()
    return canvas


def _convert_with_pillow(
    source: Path,
    target: Path,
    root: Path,
    max_size: tuple[int, int],
    target_format: str,
    previous_reason: str | None,
) -> PdfImageResult:
    details = {"path": str(source), "cache_path": str(target), "requested_size": list(max_size), "target_format": target_format}
    with perf_timer(root, "pdf.image_convert_pillow", details=details, source="pdf_image_utils", page_tool="library_record"):
        try:
            from PIL import Image as PILImage
            from PIL import ImageOps
        except Exception as exc:
            return PdfImageResult(ok=False, original_path=str(source), reason=f"Pillow unavailable: {exc}; {previous_reason or ''}".strip(), skipped=True)

        _register_heif_opener(root, source)
        try:
            with PILImage.open(source) as image:
                image = ImageOps.exif_transpose(image)
                image.thumbnail(max_size)
                if target_format == "JPEG":
                    image = _pil_image_for_jpeg(image, PILImage)
                    image.save(target, "JPEG", quality=86, optimize=True)
                else:
                    if image.mode not in {"RGB", "RGBA", "L"}:
                        image = image.convert("RGBA")
                    image.save(target, "PNG", optimize=True)
            return PdfImageResult(ok=True, pdf_safe_path=str(target), original_path=str(source), converted=True)
        except Exception as exc:
            LOGGER.debug("Pillow PDF image conversion failed for %s: %s", source, exc)
            return PdfImageResult(ok=False, original_path=str(source), reason=f"unsupported image format or decode failed: {exc}", skipped=True)


def _pil_image_for_jpeg(image, PILImage):
    if image.mode == "RGB":
        return image
    if image.mode in {"RGBA", "LA"}:
        background = PILImage.new("RGB", image.size, "white")
        background.paste(image, mask=image.getchannel("A"))
        return background
    return image.convert("RGB")


def _register_heif_opener(root: Path, source: Path) -> None:
    global _HEIF_REGISTERED
    if _HEIF_REGISTERED is not None:
        return
    try:
        from pillow_heif import register_heif_opener
    except Exception:
        _HEIF_REGISTERED = False
        if source.suffix.casefold() in {".heic", ".heif"}:
            log_perf_marker(
                root,
                "pdf.image_convert_pillow",
                details={"path": str(source), "heif_support": False, "reason": "pillow-heif not installed"},
                source="pdf_image_utils",
                page_tool="library_record",
            )
        return
    register_heif_opener()
    _HEIF_REGISTERED = True


def _skip(root: Path, source: Path, reason: str) -> PdfImageResult:
    log_perf_marker(
        root,
        "pdf.image_skipped",
        details={"path": str(source), "reason": reason},
        source="pdf_image_utils",
        page_tool="library_record",
    )
    return PdfImageResult(ok=False, original_path=str(source), reason=reason, skipped=True)


def _remember_skip(root: Path, cache_key: str, source: Path, reason: str) -> PdfImageResult:
    log_perf_marker(
        root,
        "pdf.image_convert_failed",
        details={"path": str(source), "reason": reason},
        source="pdf_image_utils",
        page_tool="library_record",
    )
    result = _skip(root, source, reason)
    _FAILED_IMAGE_PREP[cache_key] = result
    return result


__all__ = ["PdfImageResult", "prepare_image_for_pdf", "prepare_images_for_pdf"]
