"""Browser-specific, read-only document delivery with a fail-closed path policy."""

from __future__ import annotations

import io
import json
import logging
import mimetypes
import os
import re
from pathlib import Path
from urllib.parse import unquote

from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import models as db
from .errors import APIError, not_found

LOGGER = logging.getLogger("eoat_api.web_content")
_INLINE_TYPES = {"application/pdf", "image/jpeg", "image/png", "image/gif", "image/webp"}
_THUMBNAIL_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._ -]+")
_WINDOWS_PATH = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\)")
_BROWSER_MEDIA_CACHE_CONTROL = "private, max-age=300"


def approved_content_roots() -> tuple[Path, ...]:
    """Read configured browser roots; an absent or invalid setting permits nothing."""
    raw_roots = [value.strip() for value in os.getenv("EOAT_WEB_CONTENT_ROOTS", "").split(os.pathsep) if value.strip()]
    roots: list[Path] = []
    for raw_root in raw_roots:
        try:
            root = Path(raw_root).expanduser().resolve(strict=True)
        except OSError:
            LOGGER.warning("web_content_root_unavailable")
            continue
        if root.is_dir():
            roots.append(root)
    return tuple(roots)


def safe_download_name(file_name: str) -> str:
    name = _SAFE_FILENAME.sub("-", Path(file_name).name).strip(" .-")
    return name or "eoat-atlas-file"


def _mapped_storage_path(raw_path: str) -> str:
    """Map an approved Windows/UNC database path to a Debian mount, if needed."""
    if not _WINDOWS_PATH.match(raw_path) or (os.name == "nt" and re.match(r"^[A-Za-z]:[\\/]", raw_path)):
        return raw_path
    try:
        mappings = json.loads(os.getenv("EOAT_WEB_CONTENT_PATH_MAPPINGS", "[]"))
    except json.JSONDecodeError:
        LOGGER.warning("web_content_mapping_configuration_invalid")
        raise APIError(503, "WEB_CONTENT_UNAVAILABLE", "Content is not available through the web interface.") from None
    if not isinstance(mappings, list):
        raise APIError(503, "WEB_CONTENT_UNAVAILABLE", "Content is not available through the web interface.")
    raw_normalized = raw_path.replace("/", "\\")
    normalized = raw_normalized.casefold()
    for mapping in mappings:
        if not isinstance(mapping, dict):
            continue
        prefix, target = mapping.get("source_prefix"), mapping.get("target_root")
        if not isinstance(prefix, str) or not isinstance(target, str):
            continue
        source = prefix.replace("/", "\\").rstrip("\\").casefold()
        if not source or not (normalized == source or normalized.startswith(source + "\\")):
            continue
        relative = raw_normalized[len(source) :].lstrip("\\")
        parts = [part for part in relative.split("\\") if part]
        if not parts or any(part in {".", ".."} for part in parts):
            break
        return str(Path(target, *parts))
    LOGGER.warning("web_content_mapping_not_approved")
    raise APIError(503, "WEB_CONTENT_UNAVAILABLE", "Content is not available through the web interface.")


def _reject_unsafe_path(raw_path: str, roots: tuple[Path, ...]) -> Path:
    if not roots:
        raise APIError(503, "WEB_CONTENT_UNAVAILABLE", "Content is not available through the web interface.", retryable=True)
    decoded = unquote(raw_path)
    if decoded != raw_path or ".." in raw_path.replace("\\", "/").split("/"):
        LOGGER.warning("web_content_rejected_encoded_or_traversal_path")
        raise APIError(403, "WEB_CONTENT_FORBIDDEN", "Content is not available through the web interface.")
    try:
        candidate = Path(_mapped_storage_path(raw_path)).expanduser()
        if not candidate.is_absolute():
            raise ValueError("relative path")
        resolved = candidate.resolve(strict=True)
    except (OSError, ValueError):
        LOGGER.warning("web_content_rejected_missing_or_invalid_path")
        raise APIError(404, "WEB_CONTENT_UNAVAILABLE", "Content is not available through the web interface.") from None
    if not resolved.is_file() or not any(resolved.is_relative_to(root) for root in roots):
        LOGGER.warning("web_content_rejected_outside_approved_root")
        raise APIError(403, "WEB_CONTENT_FORBIDDEN", "Content is not available through the web interface.")
    return resolved


def _media_type(document: db.Document, path: Path) -> str:
    declared = (document.mime_type or "").strip().casefold()
    guessed = (mimetypes.guess_type(path.name)[0] or "").casefold()
    candidate = declared if declared in _INLINE_TYPES | {"application/octet-stream"} else guessed
    return candidate if candidate in _INLINE_TYPES | {"application/octet-stream"} else "application/octet-stream"


def _document(session: Session, document_uuid: str, *, photo_only: bool | None = None) -> db.Document:
    document = session.scalar(select(db.Document).where(db.Document.document_uuid == document_uuid))
    if document is None:
        raise not_found("Document", document_uuid)
    photo = session.scalar(select(db.Photo).where(db.Photo.document_id == document.id))
    if photo_only is True and photo is None:
        raise not_found("Photo", document_uuid)
    if photo_only is False and photo is not None:
        raise not_found("Document", document_uuid)
    return document


def content_is_available(storage_path: str) -> bool:
    """Safe metadata hint only; no path or root is exposed to clients."""
    try:
        _reject_unsafe_path(storage_path, approved_content_roots())
    except APIError:
        return False
    return True


def content_response(session: Session, document_uuid: str, *, photo_only: bool | None = None):
    document = _document(session, document_uuid, photo_only=photo_only)
    path = _reject_unsafe_path(document.storage_path, approved_content_roots())
    media_type = _media_type(document, path)
    disposition = "inline" if media_type in _INLINE_TYPES else "attachment"
    response = FileResponse(path, media_type=media_type, filename=safe_download_name(document.file_name), content_disposition_type=disposition)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = _BROWSER_MEDIA_CACHE_CONTROL
    return response


def thumbnail_response(session: Session, document_uuid: str):
    document = _document(session, document_uuid, photo_only=True)
    path = _reject_unsafe_path(document.storage_path, approved_content_roots())
    if _media_type(document, path) not in _THUMBNAIL_TYPES:
        raise APIError(409, "THUMBNAIL_UNAVAILABLE", "A thumbnail is not available for this photo.")
    try:
        from PIL import Image

        with Image.open(path) as image:
            image.thumbnail((640, 640))
            if image.mode not in {"RGB", "L"}:
                image = image.convert("RGB")
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=84, optimize=True)
    except (OSError, ValueError):
        LOGGER.warning("web_thumbnail_generation_failed")
        raise APIError(409, "THUMBNAIL_UNAVAILABLE", "A thumbnail is not available for this photo.") from None
    response = StreamingResponse(iter([buffer.getvalue()]), media_type="image/jpeg")
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = _BROWSER_MEDIA_CACHE_CONTROL
    response.headers["Content-Disposition"] = f'inline; filename="{safe_download_name(Path(document.file_name).stem)}.jpg"'
    return response
