from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest

from core.photos.photo_service import PhotoService


def test_photo_service_loads_thumbnail_and_reuses_memory_cache(qapp, tmp_path: Path) -> None:
    image_path = _write_image(tmp_path / "photos" / "thumb.png")
    service = PhotoService(tmp_path, max_workers=1)
    ready: list[tuple[str, QImage, str, str]] = []
    service.thumbnail_ready.connect(lambda photo_id, image, path, context: ready.append((photo_id, image, path, context)))

    service.request_thumbnail("photo-1", [str(image_path)], (64, 64), 90, "photos:record:1")
    assert _wait_for(qapp, lambda: len(ready) == 1)

    first = ready[0]
    assert first[0] == "photo-1"
    assert first[1].width() <= 64
    assert first[1].height() <= 64
    assert Path(first[2]) == image_path
    assert list((tmp_path / "00_Project_Admin" / "cache" / "photo_thumbnails").glob("*"))

    ready.clear()
    service.request_thumbnail("photo-1", [str(image_path)], (64, 64), 90, "photos:record:1")
    assert _wait_for(qapp, lambda: len(ready) == 1)
    assert not ready[0][1].isNull()


def test_photo_service_loads_disk_thumbnail_after_memory_eviction(qapp, tmp_path: Path) -> None:
    image_path = _write_image(tmp_path / "photos" / "disk.png")
    first = PhotoService(tmp_path, max_workers=1)
    first_ready: list[QImage] = []
    first.thumbnail_ready.connect(lambda _photo_id, image, _path, _context: first_ready.append(image))
    first.request_thumbnail("photo-2", [str(image_path)], (80, 80), 90, "photos:record:2")
    assert _wait_for(qapp, lambda: len(first_ready) == 1)

    second = PhotoService(tmp_path, max_workers=1)
    second_ready: list[QImage] = []
    second.thumbnail_ready.connect(lambda _photo_id, image, _path, _context: second_ready.append(image))
    second.request_thumbnail("photo-2", [str(image_path)], (80, 80), 90, "photos:record:2")
    assert _wait_for(qapp, lambda: len(second_ready) == 1)
    assert not second_ready[0].isNull()


def test_photo_service_reuses_larger_cached_thumbnail_for_smaller_request(qapp, tmp_path: Path) -> None:
    image_path = _write_image(tmp_path / "photos" / "large.png", size=(800, 600))
    service = PhotoService(tmp_path, max_workers=1)
    ready: list[QImage] = []
    service.thumbnail_ready.connect(lambda _photo_id, image, _path, _context: ready.append(image))

    service.request_thumbnail("photo-large", [str(image_path)], (512, 512), 90, "library:eoat_cards:page:1")
    assert _wait_for(qapp, lambda: len(ready) == 1)

    cached = service.get_cached_thumbnail("photo-large", (384, 256))
    assert cached is not None
    assert not cached.isNull()


def test_photo_service_cancelled_context_does_not_emit(qapp, tmp_path: Path) -> None:
    image_path = _write_image(tmp_path / "photos" / "cancel.png")
    service = PhotoService(tmp_path, max_workers=1)
    ready: list[QImage] = []
    service.thumbnail_ready.connect(lambda _photo_id, image, _path, _context: ready.append(image))

    service.pause_prefetch()
    service.request_thumbnail("photo-3", [str(image_path)], (64, 64), 20, "library:old")
    service.cancel_context("library:old")
    service.resume_prefetch()
    QTest.qWait(150)
    qapp.processEvents()

    assert ready == []


def test_photo_service_loads_full_image_async(qapp, tmp_path: Path) -> None:
    image_path = _write_image(tmp_path / "photos" / "full.png", size=(160, 120))
    service = PhotoService(tmp_path, max_workers=1)
    ready: list[tuple[str, QImage, str, str]] = []
    service.full_image_ready.connect(lambda photo_id, image, path, context: ready.append((photo_id, image, path, context)))

    service.request_full_image("photo-4", [str(image_path)], 100, "lightbox:photo-4")
    assert _wait_for(qapp, lambda: len(ready) == 1)

    assert ready[0][0] == "photo-4"
    assert ready[0][1].size() == QImage(str(image_path)).size()
    assert Path(ready[0][2]) == image_path


def _write_image(path: Path, *, size: tuple[int, int] = (96, 72)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = QImage(size[0], size[1], QImage.Format.Format_RGB32)
    image.fill(QColor("#168dff"))
    assert image.save(str(path))
    return path


def _wait_for(qapp, predicate, *, timeout_ms: int = 5000) -> bool:
    elapsed = 0
    while elapsed < timeout_ms:
        qapp.processEvents()
        if predicate():
            return True
        QTest.qWait(25)
        elapsed += 25
    qapp.processEvents()
    return predicate()
