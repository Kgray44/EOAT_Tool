from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


def _module():
    path = Path(__file__).parents[1] / "scripts" / "media" / "sync_eoat_media.py"
    spec = importlib.util.spec_from_file_location("sync_eoat_media", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _inventory(path: Path, source: Path, *, document_uuid: str = "00000000-0000-4000-8000-000000000001") -> Path:
    payload = {
        "version": 1,
        "entries": [
            {
                "document_uuid": document_uuid,
                "source_path": str(source),
                "file_name": source.name,
                "eoat_links": ["EOAT-001"],
            }
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_stage_and_sync_create_hash_verified_jpeg_derivative_idempotently(tmp_path: Path) -> None:
    image = pytest.importorskip("PIL.Image")
    sync = _module()
    source_root = tmp_path / "corporate"
    source_root.mkdir()
    source = source_root / "EOAT profile.jpg"
    exif = image.Exif()
    exif[274] = 6
    exif[36867] = "2026:08:21 10:20:30"
    image.new("RGB", (20, 40), "orange").save(source, exif=exif)
    inventory = _inventory(tmp_path / "inventory.json", source)
    staging_root = tmp_path / "staging"
    media_root = tmp_path / "media"

    staged = sync.stage(inventory, str(source_root), staging_root)
    assert staged["staged_count"] == 1
    first = sync.sync(staging_root / "manifest" / "staged-inventory.json", staging_root, media_root)
    manifest_path = media_root / "manifest" / "media-manifest.json"
    manifest_before = manifest_path.read_bytes()
    second = sync.sync(staging_root / "manifest" / "staged-inventory.json", staging_root, media_root)

    assert first["copied_originals"] == 1
    assert first["generated_or_repaired_derivatives"] == 1
    assert second["copied_originals"] == 0
    assert second["generated_or_repaired_derivatives"] == 0
    assert manifest_path.read_bytes() == manifest_before
    entry = json.loads(manifest_before)["entries"][0]
    assert (media_root / entry["original_relative_path"]).read_bytes() == source.read_bytes()
    with image.open(media_root / entry["web_relative_path"]) as derivative:
        assert derivative.format == "JPEG"
        assert derivative.size == (40, 20)
        assert derivative.getexif().get(36867) == "2026:08:21 10:20:30"
        assert derivative.getexif().get(34853) is None  # GPS metadata is never carried forward.


def test_sync_refuses_changed_source_without_replacing_archival_original(tmp_path: Path) -> None:
    image = pytest.importorskip("PIL.Image")
    sync = _module()
    source_root = tmp_path / "corporate"
    source_root.mkdir()
    source = source_root / "photo.jpg"
    image.new("RGB", (20, 20), "blue").save(source)
    inventory = _inventory(tmp_path / "inventory.json", source)
    staging_root = tmp_path / "staging"
    media_root = tmp_path / "media"
    sync.stage(inventory, str(source_root), staging_root)
    sync.sync(staging_root / "manifest" / "staged-inventory.json", staging_root, media_root)
    original = next((media_root / "originals").rglob("*.jpg"))
    original_hash = sync._hash_file(original)

    image.new("RGB", (20, 20), "red").save(source)
    report = sync.stage(inventory, str(source_root), staging_root)

    assert report["staged_count"] == 0
    assert report["missing_or_unresolved"] == [
        {"document_uuid": "00000000-0000-4000-8000-000000000001", "reason": "STAGING_TARGET_CONFLICT"}
    ]
    assert sync._hash_file(original) == original_hash
