from __future__ import annotations

import asyncio
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from server.eoat_api import web_content
from server.eoat_api.app import app
from server.eoat_api.errors import APIError


def _configure_root(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    monkeypatch.setenv("EOAT_WEB_CONTENT_ROOTS", str(root))


def test_content_path_accepts_file_inside_explicit_approved_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_root(monkeypatch, tmp_path)
    source = tmp_path / "setup.pdf"
    source.write_bytes(b"%PDF-1.4")

    assert web_content._reject_unsafe_path(str(source), web_content.approved_content_roots()) == source.resolve()


@pytest.mark.parametrize("stored_path", ["../secret.pdf", "%2e%2e/secret.pdf", r"..\\secret.pdf", "/tmp/other.pdf"])
def test_content_path_rejects_traversal_and_absolute_substitution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stored_path: str
) -> None:
    _configure_root(monkeypatch, tmp_path)

    with pytest.raises(APIError) as error:
        web_content._reject_unsafe_path(stored_path, web_content.approved_content_roots())

    assert str(tmp_path) not in error.value.message
    assert "secret.pdf" not in error.value.message


def test_debian_unc_mapping_uses_only_an_exact_approved_prefix(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    mounted = tmp_path / "mount"
    mounted.mkdir()
    source = mounted / "Folder" / "photo.jpg"
    source.parent.mkdir()
    source.write_bytes(b"jpg")
    monkeypatch.setenv(
        "EOAT_WEB_CONTENT_PATH_MAPPINGS",
        json.dumps([{"source_prefix": r"\\fileserver\eoat-media", "target_root": str(mounted)}]),
    )
    monkeypatch.setattr(web_content.os, "name", "posix")

    mapped = web_content._mapped_storage_path(r"\\fileserver\eoat-media\Folder\photo.jpg")
    assert mapped.replace("\\", "/").casefold() == str(source).replace("\\", "/").casefold()
    with pytest.raises(APIError):
        web_content._mapped_storage_path(r"\\fileserver\eoat-media-evil\Folder\photo.jpg")


def test_windows_unc_path_does_not_require_a_debian_mapping(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(web_content.os, "name", "nt")
    monkeypatch.delenv("EOAT_WEB_CONTENT_PATH_MAPPINGS", raising=False)

    assert web_content._mapped_storage_path(r"\\fileserver\eoat-media\Folder\photo.jpg") == r"\\fileserver\eoat-media\Folder\photo.jpg"


def test_content_response_uses_safe_filename_and_forces_active_content_download(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_root(monkeypatch, tmp_path)
    source = tmp_path / "unsafe.html"
    source.write_text("<script>alert(1)</script>", encoding="utf-8")
    document = SimpleNamespace(storage_path=str(source), mime_type="text/html", file_name='unsafe "label".html')
    monkeypatch.setattr(web_content, "_document", lambda *_args, **_kwargs: document)

    response = web_content.content_response(SimpleNamespace(), "known-document")

    assert response.media_type == "application/octet-stream"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "private, max-age=300"
    assert response.headers["content-disposition"].startswith("attachment;")
    assert "%22" not in response.headers["content-disposition"]
    assert "label" in response.headers["content-disposition"]


def test_missing_file_and_unknown_uuid_are_truthful(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_root(monkeypatch, tmp_path)
    missing = SimpleNamespace(storage_path=str(tmp_path / "missing.jpg"), mime_type="image/jpeg", file_name="missing.jpg")
    monkeypatch.setattr(web_content, "_document", lambda *_args, **_kwargs: missing)

    with pytest.raises(APIError) as error:
        web_content.content_response(SimpleNamespace(), "known-document")
    assert error.value.status_code == 404
    assert str(tmp_path) not in error.value.message


def test_thumbnail_delivery_is_nosniff_and_browser_safe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    Image = pytest.importorskip("PIL.Image")
    _configure_root(monkeypatch, tmp_path)
    source = tmp_path / "photo.png"
    Image.new("RGB", (1024, 300), "navy").save(source)
    document = SimpleNamespace(storage_path=str(source), mime_type="image/png", file_name="profile.png")
    monkeypatch.setattr(web_content, "_document", lambda *_args, **_kwargs: document)

    response = web_content.thumbnail_response(SimpleNamespace(), "known-photo")

    assert response.media_type == "image/jpeg"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "private, max-age=300"


def test_thumbnail_normalizes_jpeg_exif_orientation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    Image = pytest.importorskip("PIL.Image")
    _configure_root(monkeypatch, tmp_path)
    source = tmp_path / "rotated.jpg"
    exif = Image.Exif()
    exif[274] = 6  # Camera rotated 90 degrees clockwise.
    Image.new("RGB", (20, 40), "orange").save(source, exif=exif)
    document = SimpleNamespace(storage_path=str(source), mime_type="image/jpeg", file_name="rotated.jpg")
    monkeypatch.setattr(web_content, "_document", lambda *_args, **_kwargs: document)

    response = web_content.thumbnail_response(SimpleNamespace(), "rotated-photo")

    async def body() -> bytes:
        return b"".join([chunk async for chunk in response.body_iterator])

    with Image.open(io.BytesIO(asyncio.run(body()))) as thumbnail:
        assert thumbnail.size == (40, 20)


def test_photo_manifest_resolves_unc_record_only_to_matching_jpeg_derivative(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    Image = pytest.importorskip("PIL.Image")
    _configure_root(monkeypatch, tmp_path)
    document_uuid = "00000000-0000-4000-8000-000000000001"
    derivative = tmp_path / "web" / f"{document_uuid}.jpg"
    derivative.parent.mkdir()
    Image.new("RGB", (64, 32), "green").save(derivative)
    source_path = r"\\gwplastics.com\VT\EOAT Photos\profile.heic"
    manifest = tmp_path / "media-manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "version": 1,
                "entries": [
                    {
                        "document_uuid": document_uuid,
                        "source_path": source_path,
                        "web_relative_path": f"web/{document_uuid}.jpg",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EOAT_WEB_MEDIA_MANIFEST", str(manifest))
    document = SimpleNamespace(storage_path=source_path, mime_type="image/heic", file_name="profile.heic")
    monkeypatch.setattr(web_content, "_document", lambda *_args, **_kwargs: document)

    response = web_content.content_response(SimpleNamespace(), document_uuid, photo_only=True)

    assert response.media_type == "image/jpeg"
    assert response.headers["content-disposition"].endswith('filename="profile.jpg"')
    assert web_content.content_is_available(source_path, document_uuid=document_uuid, photo=True)


def test_photo_manifest_rejects_a_uuid_when_its_unc_source_path_does_not_match(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_root(monkeypatch, tmp_path)
    document_uuid = "00000000-0000-4000-8000-000000000001"
    manifest = tmp_path / "media-manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "version": 1,
                "entries": [
                    {
                        "document_uuid": document_uuid,
                        "source_path": r"\\gwplastics.com\VT\expected.heic",
                        "web_relative_path": f"web/{document_uuid}.jpg",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EOAT_WEB_MEDIA_MANIFEST", str(manifest))

    with pytest.raises(APIError) as error:
        web_content._manifest_photo_path(document_uuid, r"\\gwplastics.com\VT\other.heic", web_content.approved_content_roots())

    assert error.value.status_code == 404


def test_photo_manifest_rejects_forward_and_windows_style_relative_traversal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_root(monkeypatch, tmp_path)
    document_uuid = "00000000-0000-4000-8000-000000000001"
    source_path = r"\\gwplastics.com\VT\expected.heic"
    manifest = tmp_path / "media-manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "version": 1,
                "entries": [
                    {
                        "document_uuid": document_uuid,
                        "source_path": source_path,
                        "web_relative_path": r"..\outside.jpg",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EOAT_WEB_MEDIA_MANIFEST", str(manifest))

    with pytest.raises(APIError) as error:
        web_content._manifest_photo_path(document_uuid, source_path, web_content.approved_content_roots())

    assert error.value.status_code == 404


def test_content_routes_are_in_openapi() -> None:
    paths = app.openapi()["paths"]

    assert "/api/v1/web-documents/{document_uuid}/content" in paths
    assert "/api/v1/web-photos/{document_uuid}/content" in paths
    assert "/api/v1/web-photos/{document_uuid}/thumbnail" in paths
    assert "storage_path" not in app.openapi()["components"]["schemas"]["WebDocumentMetadata"]["properties"]
