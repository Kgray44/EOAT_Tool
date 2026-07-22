from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from server.eoat_api import web_content
from server.eoat_api.app import app, evaluate_web_fit_check
from server.eoat_api.contracts import WebFitCheckRequest
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


def test_content_path_rejects_symlink_escape(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_root(monkeypatch, tmp_path)
    outside = tmp_path.parent / "outside-web-content.txt"
    outside.write_text("private", encoding="utf-8")
    escaped = tmp_path / "escaped.txt"
    try:
        escaped.symlink_to(outside)
    except OSError:
        pytest.skip("Symlink creation is unavailable on this Windows test host.")

    with pytest.raises(APIError) as error:
        web_content._reject_unsafe_path(str(escaped), web_content.approved_content_roots())

    assert "outside-web-content" not in error.value.message


def test_windows_storage_path_uses_only_an_exact_approved_mapping(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    mounted = tmp_path / "mount"
    mounted.mkdir()
    source = mounted / "Folder" / "photo.jpg"
    source.parent.mkdir()
    source.write_bytes(b"jpg")
    _configure_root(monkeypatch, mounted)
    monkeypatch.setenv(
        "EOAT_WEB_CONTENT_PATH_MAPPINGS",
        json.dumps([{"source_prefix": r"\\fileserver\eoat-media", "target_root": str(mounted)}]),
    )

    assert web_content._reject_unsafe_path(r"\\fileserver\eoat-media\Folder\photo.jpg", web_content.approved_content_roots()) == source.resolve()
    with pytest.raises(APIError):
        web_content._reject_unsafe_path(r"\\fileserver\eoat-media-evil\Folder\photo.jpg", web_content.approved_content_roots())


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


def test_unknown_uuid_does_not_disclose_storage_details() -> None:
    class EmptySession:
        def scalar(self, _statement):
            return None

    with pytest.raises(APIError) as error:
        web_content._document(EmptySession(), "unknown-uuid")

    assert error.value.status_code == 404
    assert "unknown-uuid" in error.value.message


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


def test_web_fit_check_forces_non_persisting_request(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    class FakeService:
        def __init__(self, session):
            captured["session"] = session

        def fit_check(self, request):
            captured["request"] = request
            return {"overall_result": "INVALID_INPUT"}

    monkeypatch.setattr("server.eoat_api.app.AtlasService", FakeService)
    result = evaluate_web_fit_check(
        WebFitCheckRequest(machine_number="M-1", tool_number="T-1", eoat_identifier="E-1"), SimpleNamespace()
    )

    assert captured["request"].persist is False
    assert result == {"overall_result": "INVALID_INPUT"}


def test_web_content_and_fit_check_routes_are_in_openapi() -> None:
    paths = app.openapi()["paths"]

    assert "/api/v1/web-documents/{document_uuid}/content" in paths
    assert "/api/v1/web-photos/{document_uuid}/thumbnail" in paths
    assert "/api/v1/web-fit-checks/evaluate" in paths
    assert "storage_path" not in app.openapi()["components"]["schemas"]["WebDocumentMetadata"]["properties"]
