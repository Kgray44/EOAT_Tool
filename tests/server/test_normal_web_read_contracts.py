from __future__ import annotations

from fastapi.testclient import TestClient

from server.eoat_api.app import app, repository, service
from server.eoat_api.contracts import (
    DataStatus,
    DocumentMetadata,
    EOATProfile,
    EOATSummary,
    MachineProfile,
    MachineSummary,
    PaginationMetadata,
    PhotoMetadata,
    ToolProfile,
    ToolSummary,
)
from server.eoat_api.database.session import get_runtime_session
from server.eoat_api.repositories import AtlasRepository


class _Session:
    def scalar(self, *_args, **_kwargs):
        return type("Entity", (), {"id": 1})()


class _Repository:
    session = _Session()

    def list_eoats(self, **_kwargs):
        return (
            [
                EOATSummary(
                    business_identifier="CL-EOAT-0054",
                    is_active=True,
                    row_version=1,
                    photo_document_uuid="browser-safe-profile-photo",
                    photo_available_through_web=True,
                )
            ],
            PaginationMetadata(page=1, page_size=50, total=1, pages=1),
        )

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


class _Rows:
    def all(self):
        return []


class _FitCheckSession:
    def scalar(self, *_args, **_kwargs):
        return None

    def scalars(self, *_args, **_kwargs):
        return _Rows()

    def execute(self, *_args, **_kwargs):
        return _Rows()


def _client():
    app.dependency_overrides[repository] = _Repository
    return TestClient(app)


def test_normal_profiles_and_safe_document_contracts_are_same_backend_routes():
    with _client() as client:
        summary = client.get("/api/v1/eoats").json()["items"][0]
        assert summary["photo_document_uuid"] == "browser-safe-profile-photo"
        assert summary["photo_available_through_web"] is True
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


def test_normal_fit_check_options_are_a_read_only_browser_contract():
    app.dependency_overrides[get_runtime_session] = _FitCheckSession
    with TestClient(app) as client:
        response = client.get("/api/v1/web-fit-checks/options")
    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json() == {
        "machines": [],
        "tools": [],
        "eoats": [],
        "warnings": [],
        "unresolved_inputs": [],
        "query_mode": "recommendations",
        "query_slot": None,
    }


def test_typed_fit_check_search_uses_only_the_requested_authoritative_catalog_slot(monkeypatch):
    page = PaginationMetadata(page=1, page_size=50, total=1, pages=1)

    def machines(_self, *, search, page_size, active):
        assert (search, page_size, active) == ("40", 50, True)
        return [
            MachineSummary(
                machine_number="040", machine_name="Global Machine 040", plant_code="P4", is_active=True, row_version=1
            )
        ], page

    def tools(_self, *, search, page_size, active):
        assert (search, page_size, active) == ("461", 50, True)
        return [
            ToolSummary(business_identifier="T-461", display_name="Global Tool 461", is_active=True, row_version=1)
        ], page

    def eoats(_self, *, search, page_size, active):
        assert (search, page_size, active) == ("0042", 50, True)
        return [
            EOATSummary(business_identifier="E-0042", display_name="Global EOAT 0042", is_active=True, row_version=1)
        ], page

    monkeypatch.setattr(AtlasRepository, "list_machines", machines)
    monkeypatch.setattr(AtlasRepository, "list_tools", tools)
    monkeypatch.setattr(AtlasRepository, "list_eoats", eoats)
    app.dependency_overrides[get_runtime_session] = _FitCheckSession
    try:
        with TestClient(app) as client:
            machine = client.get("/api/v1/web-fit-checks/options?search_slot=machine&search=40")
            tool = client.get("/api/v1/web-fit-checks/options?search_slot=tool&search=461")
            eoat = client.get("/api/v1/web-fit-checks/options?search_slot=eoat&search=0042")
    finally:
        app.dependency_overrides.clear()
    assert machine.json()["machines"] == [{"identifier": "040", "label": "Global Machine 040", "plant_code": "P4"}]
    assert tool.json()["tools"] == [{"identifier": "T-461", "label": "Global Tool 461", "plant_code": None}]
    assert eoat.json()["eoats"] == [{"identifier": "E-0042", "label": "Global EOAT 0042", "plant_code": None}]


def test_normal_browser_data_status_has_safe_freshness_evidence():
    class _DataStatusService:
        def data_status(self):
            return DataStatus(
                data_last_modified_at="2026-08-20T12:00:00Z",
                data_revision=42,
                server_time="2026-08-20T12:01:00Z",
            )

    app.dependency_overrides[service] = _DataStatusService
    with TestClient(app) as client:
        response = client.get("/api/v1/data-status")
    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json() == {
        "status": "available",
        "data_last_modified_at": "2026-08-20T12:00:00Z",
        "server_time": "2026-08-20T12:01:00Z",
        "data_revision": 42,
    }
