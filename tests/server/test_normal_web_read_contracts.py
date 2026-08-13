from __future__ import annotations

from fastapi.testclient import TestClient

from server.eoat_api.app import app, repository
from server.eoat_api.contracts import DocumentMetadata, EOATProfile, MachineProfile, PhotoMetadata, ToolProfile


class _Session:
    def scalar(self, *_args, **_kwargs):
        return type("Entity", (), {"id": 1})()


class _Repository:
    session = _Session()

    def eoat(self, identifier: str):
        return EOATProfile(business_identifier=identifier, is_active=True, row_version=1)

    def machine(self, number: str):
        return MachineProfile(machine_number=number, is_active=True, row_version=1)

    def tool(self, identifier: str):
        return ToolProfile(business_identifier=identifier, is_active=True, row_version=1)

    def eoat_relationships(self, _identifier: str):
        return []

    def documents(self, entity_type: str, _entity_id: int, *, photos_only: bool = False):
        document = DocumentMetadata(
            document_uuid=f"{entity_type}-document",
            title="Safe document",
            file_name="safe.pdf",
            storage_path=r"\\internal-server\private\safe.pdf",
        )
        if not photos_only:
            return [document]
        return [
            PhotoMetadata(
                **document.model_dump(),
                photo_view_type="overview",
                caption="Safe photo",
            )
        ]


def _client():
    app.dependency_overrides[repository] = _Repository
    return TestClient(app)


def test_normal_profiles_and_safe_document_contracts_are_same_backend_routes():
    with _client() as client:
        assert client.get("/api/v1/eoats/CL-EOAT-0054").json()["business_identifier"] == "CL-EOAT-0054"
        assert client.get("/api/v1/machines/27").json()["machine_number"] == "27"
        assert client.get("/api/v1/tools/4611380030").json()["business_identifier"] == "4611380030"
        for path in (
            "/api/v1/eoats/CL-EOAT-0054/documents",
            "/api/v1/eoats/CL-EOAT-0054/photos",
            "/api/v1/machines/27/documents",
            "/api/v1/tools/4611380030/photos",
        ):
            payload = client.get(path).json()
            assert payload and "storage_path" not in payload[0]
            assert "path_available" not in payload[0]
            assert payload[0]["content_delivery_state"] == "NOT_AVAILABLE_THROUGH_WEB"
    app.dependency_overrides.clear()
