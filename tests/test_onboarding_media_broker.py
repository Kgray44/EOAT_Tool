from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


def _module():
    path = Path(__file__).parents[1] / "deployment" / "privileged" / "eoat_onboarding_media_broker.py"
    spec = importlib.util.spec_from_file_location("eoat_onboarding_media_broker", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _broker(tmp_path: Path):
    module = _module()
    staging = tmp_path / "staging"
    media = tmp_path / "media"
    for path in (staging, media / "originals", media / "web", media / "manifest"):
        path.mkdir(parents=True, exist_ok=True)
    return module, module.Broker(module.BrokerConfig(staging, media, media / "pending", tmp_path / "broker.sock")), staging, media


def _request(source: Path, *, photo: bool = True) -> dict[str, object]:
    return {
        "operation": "promote",
        "eoat_identifier": "P4-EOAT-0201",
        "items": [
            {
                "media_id": 1,
                "document_uuid": "00000000-0000-4000-8000-000000000001",
                "source_path": str(source),
                "file_name": source.name,
                "is_photo": photo,
            }
        ],
    }


def test_promote_is_hash_verified_visible_to_the_normal_web_media_resolver_and_confirmation_removes_only_temporary_staging(
    monkeypatch, tmp_path: Path
) -> None:
    image = pytest.importorskip("PIL.Image")
    _module_value, broker, staging, media = _broker(tmp_path)
    source = staging / "draft-1" / "front.jpg"
    source.parent.mkdir()
    image.new("RGB", (20, 40), "orange").save(source)

    result = broker.handle(_request(source))
    promoted = result["items"][0]
    original = Path(promoted["storage_path"])
    manifest = json.loads((media / "manifest" / "media-manifest.json").read_text(encoding="utf-8"))

    assert result["ok"] is True
    assert original.is_file()
    assert original.read_bytes() == source.read_bytes()
    assert manifest["entries"][0]["source_path"] == str(original)
    assert (media / manifest["entries"][0]["web_relative_path"]).is_file()
    assert source.is_file()
    monkeypatch.setenv("EOAT_WEB_CONTENT_ROOTS", str(media))
    monkeypatch.setenv("EOAT_WEB_MEDIA_MANIFEST", str(media / "manifest" / "media-manifest.json"))
    from server.eoat_api import web_content

    resolved = web_content._manifest_photo_path(promoted["document_uuid"], str(original), web_content.approved_content_roots())
    assert resolved is not None and resolved.path.is_file() and resolved.media_type == "image/jpeg"

    broker.handle({"operation": "confirm", "promotion_id": result["promotion_id"]})

    assert not source.exists()
    assert original.is_file()
    assert not list((media / "pending").glob("*.json"))


def test_compensation_removes_uncommitted_media_and_restores_manifest_without_touching_staging(tmp_path: Path) -> None:
    image = pytest.importorskip("PIL.Image")
    _module_value, broker, staging, media = _broker(tmp_path)
    source = staging / "draft-1" / "front.jpg"
    source.parent.mkdir()
    image.new("RGB", (20, 20), "blue").save(source)

    result = broker.handle(_request(source))
    original = Path(result["items"][0]["storage_path"])
    broker.handle({"operation": "compensate", "promotion_id": result["promotion_id"]})

    assert source.is_file()
    assert not original.exists()
    assert json.loads((media / "manifest" / "media-manifest.json").read_text(encoding="utf-8"))["entries"] == []
    assert not list((media / "pending").glob("*.json"))


def test_promote_rejects_staging_symlink_and_does_not_publish_it(tmp_path: Path) -> None:
    _module_value, broker, staging, media = _broker(tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_text("private", encoding="utf-8")
    source = staging / "draft-1" / "front.jpg"
    source.parent.mkdir()
    try:
        source.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks are unavailable in this test environment")

    with pytest.raises(Exception, match="approved regular file"):
        broker.handle(_request(source, photo=False))

    assert not list((media / "originals").rglob("*"))
