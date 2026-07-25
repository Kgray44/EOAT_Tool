from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from server.eoat_api import app as api
from server.eoat_api.contracts import DocumentMetadata, MachineProfile, PhotoMetadata


class FakeRepository:
    def __init__(self, documents):
        self._documents = documents
        self.session = SimpleNamespace(scalar=lambda _statement: SimpleNamespace(id=27))

    def machine(self, number, *, plant_code=None):
        if number != "27":
            return None
        return MachineProfile(plant_code="P4", machine_number="27", is_active=True, row_version=1)

    def documents(self, entity_type, entity_id, *, photos_only=False):
        assert (entity_type, entity_id) == ("machine", 27)
        return [item for item in self._documents if isinstance(item, PhotoMetadata) is photos_only]


def document() -> DocumentMetadata:
    return DocumentMetadata(document_uuid="document-27", title="Machine instructions", file_name="instructions.pdf", storage_path="/srv/private/instructions.pdf")


def photo() -> PhotoMetadata:
    return PhotoMetadata(document_uuid="photo-27", title="Machine photo", file_name="photo.jpg", storage_path="/srv/private/photo.jpg")


def test_machine_web_content_uses_browser_safe_typed_metadata(monkeypatch):
    monkeypatch.setattr(api, "content_is_available", lambda _path: False)
    repo = FakeRepository([document(), photo()])
    documents = api.machine_web_documents("27", repo=repo)
    photos = api.machine_web_photos("27", repo=repo)
    assert [item.document_uuid for item in documents] == ["document-27"]
    assert [item.document_uuid for item in photos] == ["photo-27"]
    assert "storage_path" not in documents[0].model_dump()


def test_machine_web_content_empty_and_unknown_machine_contracts():
    repo = FakeRepository([])
    assert api.machine_web_documents("27", repo=repo) == []
    assert api.machine_web_photos("27", repo=repo) == []
    with pytest.raises(HTTPException) as missing:
        api.machine_web_documents("missing", repo=repo)
    assert missing.value.status_code == 404


def test_machine_web_content_routes_are_declared_in_openapi():
    paths = api.app.openapi()["paths"]
    assert "/api/v1/machines/{number}/web-documents" in paths
    assert "/api/v1/machines/{number}/web-photos" in paths


def test_machine_profile_contract_excludes_raw_audit_evidence_from_browser_json():
    """Machine profile metadata must never carry imported path-bearing audit rows."""
    profile = MachineProfile(
        plant_code="P4",
        machine_number="nonsequential-machine",
        is_active=True,
        row_version=1,
        audit_evidence=[{"Photo Folder/Link": r"\\internal\\Cell_Photos\\machine"}],
    )

    assert "audit_evidence" not in profile.model_dump()
    properties = api.app.openapi()["components"]["schemas"]["MachineProfile"]["properties"]
    assert "audit_evidence" not in properties
