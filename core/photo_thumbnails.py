from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .safe_files import ensure_directory

SUPPORTED_PHOTO_PREVIEW_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".heic", ".heif"})

STATUS_READY = "ready"
STATUS_NOT_READY = "not_ready"
STATUS_MISSING = "missing"
STATUS_UNSUPPORTED = "unsupported"
STATUS_ERROR = "error"

_HEIF_REGISTERED = False


@dataclass(frozen=True)
class PhotoThumbnailCacheKey:
    absolute_path: str
    modified_time_ns: int
    file_size: int

    @property
    def digest(self) -> str:
        payload = f"{self.absolute_path}\0{self.modified_time_ns}\0{self.file_size}".encode("utf-8", errors="replace")
        return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class PhotoThumbnailResult:
    source_path: Path
    status: str
    thumbnail_path: Path | None = None
    cache_key: str = ""
    width: int | None = None
    height: int | None = None
    captured_at: str = ""
    error: str = ""

    @property
    def ready(self) -> bool:
        return self.status == STATUS_READY and self.thumbnail_path is not None and self.thumbnail_path.exists()


class ThumbnailService:
    def __init__(self, project_root: str | Path, *, cache_dir: str | Path | None = None, max_side: int = 640):
        self.project_root = Path(project_root)
        self.cache_dir = Path(cache_dir) if cache_dir is not None else self.project_root / ".cache" / "photo_thumbnails"
        self.max_side = max(64, int(max_side))

    def is_supported(self, path: str | Path) -> bool:
        return is_supported_photo_extension(path)

    def cache_key(self, path: str | Path) -> PhotoThumbnailCacheKey:
        return photo_thumbnail_cache_key(path)

    def cached_thumbnail(self, path: str | Path) -> PhotoThumbnailResult:
        source = Path(path)
        if not self.is_supported(source):
            return PhotoThumbnailResult(source, STATUS_UNSUPPORTED, error=f"Unsupported image extension: {source.suffix}")
        try:
            key = self.cache_key(source)
        except FileNotFoundError:
            return PhotoThumbnailResult(source, STATUS_MISSING, error=f"Photo file is missing: {source}")
        except OSError as exc:
            return PhotoThumbnailResult(source, STATUS_ERROR, error=f"Could not inspect photo: {exc}")
        thumbnail_path = self._thumbnail_path(key)
        metadata_path = self._metadata_path(key)
        if not thumbnail_path.exists():
            return PhotoThumbnailResult(source, STATUS_NOT_READY, cache_key=key.digest)
        metadata = _read_metadata(metadata_path)
        return PhotoThumbnailResult(
            source_path=source,
            status=STATUS_READY,
            thumbnail_path=thumbnail_path,
            cache_key=key.digest,
            width=_optional_int(metadata.get("width")),
            height=_optional_int(metadata.get("height")),
            captured_at=str(metadata.get("captured_at") or ""),
        )

    def get_thumbnail(self, path: str | Path) -> PhotoThumbnailResult:
        cached = self.cached_thumbnail(path)
        if cached.status != STATUS_NOT_READY:
            return cached

        source = Path(path)
        try:
            key = self.cache_key(source)
        except FileNotFoundError:
            return PhotoThumbnailResult(source, STATUS_MISSING, error=f"Photo file is missing: {source}")
        except OSError as exc:
            return PhotoThumbnailResult(source, STATUS_ERROR, error=f"Could not inspect photo: {exc}")

        image_api = _load_pillow(source)
        if isinstance(image_api, str):
            return PhotoThumbnailResult(source, STATUS_ERROR, cache_key=key.digest, error=image_api)
        Image, ImageOps, UnidentifiedImageError = image_api

        thumbnail_path = self._thumbnail_path(key)
        metadata_path = self._metadata_path(key)
        try:
            with Image.open(source) as image:
                captured_at = _captured_at_from_image(image)
                image = ImageOps.exif_transpose(image)
                width, height = image.size
                image.thumbnail((self.max_side, self.max_side), Image.Resampling.LANCZOS)
                if image.mode != "RGB":
                    image = image.convert("RGB")
                ensure_directory(thumbnail_path.parent)
                temp_path = thumbnail_path.with_suffix(".tmp.jpg")
                image.save(temp_path, format="JPEG", quality=86, optimize=True)
                Path(temp_path).replace(thumbnail_path)
                _write_metadata(
                    metadata_path,
                    {
                        "source_path": str(source),
                        "cache_key": key.digest,
                        "width": width,
                        "height": height,
                        "captured_at": captured_at,
                        "source_modified_time_ns": key.modified_time_ns,
                        "source_file_size": key.file_size,
                    },
                )
        except UnidentifiedImageError as exc:
            return PhotoThumbnailResult(source, STATUS_ERROR, cache_key=key.digest, error=f"Could not read image: {exc}")
        except OSError as exc:
            return PhotoThumbnailResult(source, STATUS_ERROR, cache_key=key.digest, error=f"Could not create preview: {exc}")

        return PhotoThumbnailResult(
            source_path=source,
            status=STATUS_READY,
            thumbnail_path=thumbnail_path,
            cache_key=key.digest,
            width=width,
            height=height,
            captured_at=captured_at,
        )

    def _thumbnail_path(self, key: PhotoThumbnailCacheKey) -> Path:
        return self.cache_dir / f"{key.digest}.jpg"

    def _metadata_path(self, key: PhotoThumbnailCacheKey) -> Path:
        return self.cache_dir / f"{key.digest}.json"


def is_supported_photo_extension(path: str | Path) -> bool:
    return Path(path).suffix.lower() in SUPPORTED_PHOTO_PREVIEW_EXTENSIONS


def photo_thumbnail_cache_key(path: str | Path) -> PhotoThumbnailCacheKey:
    source = Path(path)
    stat = source.stat()
    return PhotoThumbnailCacheKey(
        absolute_path=_absolute_path_text(source),
        modified_time_ns=stat.st_mtime_ns,
        file_size=stat.st_size,
    )


def _absolute_path_text(path: Path) -> str:
    try:
        return os.path.abspath(path)
    except OSError:
        return str(path.absolute())


def _load_pillow(source: Path):
    try:
        from PIL import Image, ImageOps, UnidentifiedImageError
    except ImportError:
        return "Pillow is required for photo previews. Install Pillow to enable thumbnail generation."

    if source.suffix.lower() in {".heic", ".heif"}:
        message = _register_heif_opener()
        if message:
            return message
    return Image, ImageOps, UnidentifiedImageError


def _register_heif_opener() -> str:
    global _HEIF_REGISTERED
    if _HEIF_REGISTERED:
        return ""
    try:
        from pillow_heif import register_heif_opener
    except ImportError:
        return "HEIC/HEIF previews require pillow-heif. Install pillow-heif to preview iPhone HEIC photos."
    register_heif_opener()
    _HEIF_REGISTERED = True
    return ""


def _captured_at_from_image(image) -> str:
    try:
        exif = image.getexif()
    except Exception:
        return ""
    for tag in (36867, 306, 36868):
        value = exif.get(tag)
        if value:
            return _format_exif_datetime(str(value))
    return ""


def _format_exif_datetime(value: str) -> str:
    text = value.strip()
    if len(text) >= 19 and text[4] == ":" and text[7] == ":":
        return f"{text[0:4]}-{text[5:7]}-{text[8:10]} {text[11:19]}"
    return text


def _read_metadata(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_metadata(path: Path, metadata: dict[str, Any]) -> None:
    ensure_directory(path.parent)
    path.write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")


def _optional_int(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


__all__ = [
    "PhotoThumbnailCacheKey",
    "PhotoThumbnailResult",
    "SUPPORTED_PHOTO_PREVIEW_EXTENSIONS",
    "STATUS_ERROR",
    "STATUS_MISSING",
    "STATUS_NOT_READY",
    "STATUS_READY",
    "STATUS_UNSUPPORTED",
    "ThumbnailService",
    "is_supported_photo_extension",
    "photo_thumbnail_cache_key",
]
