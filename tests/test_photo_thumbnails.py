from __future__ import annotations

import pytest

from core.photo_thumbnails import (
    STATUS_ERROR,
    STATUS_MISSING,
    STATUS_READY,
    ThumbnailService,
    is_supported_photo_extension,
    photo_thumbnail_cache_key,
)


def test_photo_thumbnail_cache_key_uses_path_mtime_and_size(tmp_path):
    photo = tmp_path / "IMG_5398.jpg"
    photo.write_bytes(b"first")

    first = photo_thumbnail_cache_key(photo)
    photo.write_bytes(b"second-version")
    second = photo_thumbnail_cache_key(photo)

    assert first.absolute_path == str(photo.resolve())
    assert first.file_size == 5
    assert second.file_size == len(b"second-version")
    assert first.digest != second.digest


def test_supported_photo_preview_extensions_include_phone_formats():
    supported = ["photo.jpg", "photo.JPEG", "photo.png", "IMG_5398.HEIC", "IMG_5398.heif"]
    unsupported = ["notes.txt", "photo.gif", "photo.webp"]

    assert all(is_supported_photo_extension(name) for name in supported)
    assert not any(is_supported_photo_extension(name) for name in unsupported)


def test_thumbnail_service_handles_missing_and_corrupt_images_safely(tmp_path):
    service = ThumbnailService(tmp_path)
    missing = service.get_thumbnail(tmp_path / "missing.jpg")
    corrupt_path = tmp_path / "corrupt.png"
    corrupt_path.write_bytes(b"not a real image")
    corrupt = service.get_thumbnail(corrupt_path)

    assert missing.status == STATUS_MISSING
    assert corrupt.status == STATUS_ERROR
    assert not missing.ready
    assert not corrupt.ready


def test_thumbnail_service_generates_cached_preview_with_dimensions(tmp_path):
    Image = pytest.importorskip("PIL.Image")
    photo = tmp_path / "IMG_5398.png"
    Image.new("RGB", (80, 40), color=(20, 120, 200)).save(photo)
    service = ThumbnailService(tmp_path, max_side=64)

    generated = service.get_thumbnail(photo)
    cached = service.cached_thumbnail(photo)

    assert generated.status == STATUS_READY
    assert generated.thumbnail_path is not None
    assert generated.thumbnail_path.exists()
    assert generated.thumbnail_path.parent == tmp_path / ".cache" / "photo_thumbnails"
    assert generated.width == 80
    assert generated.height == 40
    assert cached.ready
    assert cached.thumbnail_path == generated.thumbnail_path


def test_thumbnail_service_generates_heic_preview_when_pillow_heif_is_available(tmp_path):
    Image = pytest.importorskip("PIL.Image")
    pillow_heif = pytest.importorskip("pillow_heif")
    pillow_heif.register_heif_opener()
    photo = tmp_path / "IMG_5398.HEIC"
    Image.new("RGB", (120, 80), color=(30, 90, 140)).save(photo)
    service = ThumbnailService(tmp_path, max_side=64)

    generated = service.get_thumbnail(photo)

    assert generated.status == STATUS_READY
    assert generated.thumbnail_path is not None
    assert generated.thumbnail_path.exists()
    assert generated.width == 120
    assert generated.height == 80
