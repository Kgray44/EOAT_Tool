from server.eoat_api.app import _web_document_metadata, app
from server.eoat_api.contracts import DocumentMetadata, PhotoMetadata


def test_browser_metadata_excludes_internal_storage_path() -> None:
    value = DocumentMetadata(
        document_uuid="document-1",
        title="Setup sheet",
        file_name="setup.pdf",
        storage_path=r"\\internal\restricted\setup.pdf",
    )

    payload = _web_document_metadata(value).model_dump()

    assert "storage_path" not in payload
    assert payload["content_delivery_state"] == "NOT_AVAILABLE_THROUGH_WEB"


def test_browser_photo_metadata_preserves_photo_fields_without_path() -> None:
    value = PhotoMetadata(
        document_uuid="photo-1",
        title="Profile photo",
        file_name="profile.jpg",
        storage_path=r"C:\restricted\profile.jpg",
        is_profile_photo=True,
    )

    payload = _web_document_metadata(value).model_dump()

    assert payload["is_profile_photo"] is True
    assert "storage_path" not in payload


def test_profile_openapi_declares_typed_and_browser_safe_endpoints() -> None:
    schema = app.openapi()

    assert schema["paths"]["/api/v1/eoats/{identifier}"]["get"]["responses"]["200"]
    assert schema["paths"]["/api/v1/eoats/{identifier}/web-documents"]["get"]["responses"]["200"]
    assert "storage_path" not in schema["components"]["schemas"]["WebDocumentMetadata"]["properties"]
