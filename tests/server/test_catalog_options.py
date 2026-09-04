from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from server.eoat_api.app import app, repository


class _CatalogRepository:
    def lookups(self, kind):
        return {
            kind: [
                SimpleNamespace(code="verified", display_name="Verified"),
                SimpleNamespace(code="incompatible", display_name="Incompatible"),
            ]
        }

    def list_machines(self, **_kwargs):
        return [SimpleNamespace(plant_code="VT", machine_number="M-12", machine_name="Press line")], None

    def list_tools(self, **_kwargs):
        return [SimpleNamespace(business_identifier="TOOL-7", display_name="Seven")], None

    def list_eoats(self, **_kwargs):
        return [SimpleNamespace(business_identifier="EOAT-7", display_name="Picker")], None


def test_catalog_options_adapts_authoritative_lookup_and_catalog_values():
    app.dependency_overrides[repository] = lambda: _CatalogRepository()
    try:
        with TestClient(app) as client:
            status = client.get("/api/v1/catalog-options/compatibility_status?query=ver")
            machines = client.get("/api/v1/catalog-options/machine")
            tools = client.get("/api/v1/catalog-options/tool")
    finally:
        app.dependency_overrides.pop(repository, None)

    assert status.status_code == 200
    assert status.json() == [{"value": "verified", "label": "Verified"}]
    assert machines.json() == [{"value": "VT::M-12", "label": "VT · M-12 · Press line"}]
    assert tools.json() == [{"value": "TOOL-7", "label": "Seven"}]

