from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from core.data_gateway.cache_repository import CacheRepository
from core.data_gateway.configuration import GatewayConfiguration
from core.data_gateway.exceptions import ApiUnavailableError, IncompatibleServerError
from core.data_gateway.gateway import AtlasDataGateway
from core.data_gateway.models import ConnectivityMode
from server.eoat_api.app import app, database_error
from server.eoat_api.database import models as db
from server.eoat_api.database.session import create_session_factory
from tests.fixtures.mysql_sanctioned import reset_and_load_sanctioned_fixture

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module", autouse=True)
def sanctioned_database():
    reset_and_load_sanctioned_fixture()


@pytest.fixture(scope="module")
def api():
    with TestClient(app) as client:
        yield client


class ApiClientAdapter:
    def __init__(self, client: TestClient):
        self.client = client

    def _get(self, path, **params):
        response = self.client.get(path, params=params)
        response.raise_for_status()
        return response.json()

    def health(self):
        return self._get("/api/v1/health")

    def home_summary(self):
        return self._get("/api/v1/home-summary")

    def search(self, query, limit=50):
        return self._get("/api/v1/search", q=query, limit=limit)

    def list_eoats(self, **params):
        return self._get("/api/v1/eoats", **params)

    def get_eoat(self, value):
        return self._get(f"/api/v1/eoats/{value}")

    def get_eoat_history(self, value, **params):
        return self._get(f"/api/v1/eoats/{value}/history", **params)

    def get_eoat_documents(self, value):
        return self._get(f"/api/v1/eoats/{value}/documents")

    def get_eoat_photos(self, value):
        return self._get(f"/api/v1/eoats/{value}/photos")

    def list_machines(self, **params):
        return self._get("/api/v1/machines", **params)

    def get_machine(self, value, *, plant_code=None):
        return self._get(f"/api/v1/machines/{value}", plant_code=plant_code)

    def list_tools(self, **params):
        return self._get("/api/v1/tools", **params)

    def get_tool(self, value):
        return self._get(f"/api/v1/tools/{value}")

    def evaluate_fit_check(self, machine, tool, eoat):
        response = self.client.post(
            "/api/v1/fit-checks/evaluate",
            json={"machine_number": machine, "tool_number": tool, "eoat_identifier": eoat},
        )
        response.raise_for_status()
        return response.json()

    def alternatives(self, machine, tool, eoat):
        return self._get(
            "/api/v1/compatibility/alternatives", machine_number=machine, tool_number=tool, eoat_identifier=eoat
        )

    def setup_packet_data(self, machine, tool, eoat):
        return self._get("/api/v1/setup-packets/data", machine_number=machine, tool_number=tool, eoat_identifier=eoat)

    def sync_status(self):
        return self._get("/api/v1/sync/status")

    def changes(self, cursor):
        return self._get("/api/v1/sync/changes", after_cursor=cursor)

    def snapshot(self):
        return self._get("/api/v1/sync/snapshot")

    def close(self):
        pass


def test_health_version_and_schema(api):
    health = api.get("/api/v1/health")
    assert health.status_code == 200
    payload = health.json()
    assert payload["database_reachable"] is True
    assert payload["compatible"] is True
    assert payload["current_schema_revision"] == "20260721_0008"
    assert api.get("/api/v1/version").json()["api_version"] == "1.4.0"
    assert api.get("/api/v1/schema-status").json()["compatible"] is True


def test_database_outage_is_normalized_to_503():
    response = asyncio.run(database_error(None, OperationalError("SELECT 1", {}, RuntimeError("simulated outage"))))
    assert response.status_code == 503
    assert b'DATABASE_UNAVAILABLE' in response.body


def test_paginated_filtered_entity_contracts(api):
    eoats = api.get("/api/v1/eoats", params={"page": 1, "page_size": 5})
    assert eoats.status_code == 200
    assert len(eoats.json()["items"]) == 5
    assert eoats.json()["pagination"]["total"] == 56
    machines = api.get("/api/v1/machines", params={"page_size": 250}).json()
    assert machines["pagination"]["total"] == 11
    tools = api.get("/api/v1/tools", params={"page_size": 250}).json()
    assert tools["pagination"]["total"] == 11
    filtered = api.get("/api/v1/eoats", params={"search": "DEMO-P4-EOAT"}).json()
    assert filtered["pagination"]["total"] > 0


def test_profiles_relationships_history_documents_and_photos(api):
    eoat = api.get("/api/v1/eoats/DEMO-P4-EOAT-0002")
    assert eoat.status_code == 200
    assert eoat.json()["audit_evidence"]
    assert api.get("/api/v1/eoats/DEMO-P4-EOAT-0002/relationships").status_code == 200
    history = api.get("/api/v1/eoats/DEMO-P4-EOAT-0001/history", params={"page_size": 5}).json()
    assert history["pagination"]["total"] >= 1
    assert len(history["items"]) <= 5
    assert history["items"][0]["event_id"]
    assert history["items"][0]["event_category"]
    assert api.get("/api/v1/eoats/DEMO-P4-EOAT-0002/documents").status_code == 200
    assert api.get("/api/v1/eoats/DEMO-P4-EOAT-0002/photos").status_code == 200
    machine_number = eoat.json()["relationships"][0]["identifier"]
    assert api.get(f"/api/v1/machines/{machine_number}").status_code == 200
    tool = next(item["identifier"] for item in eoat.json()["relationships"] if item["relationship_type"] == "tool")
    assert api.get(f"/api/v1/tools/{tool}").status_code == 200
    assert api.get("/api/v1/eoats/DOES-NOT-EXIST").status_code == 404


def test_history_contract_pagination_sort_filter_search_and_empty_states(api):
    first = api.get("/api/v1/eoats/DEMO-P4-EOAT-0001/history", params={"page": 1, "page_size": 2}).json()
    second = api.get("/api/v1/eoats/DEMO-P4-EOAT-0001/history", params={"page": 2, "page_size": 2}).json()
    assert first["pagination"]["pages"] >= 2
    assert {item["event_id"] for item in first["items"]}.isdisjoint(
        {item["event_id"] for item in second["items"]}
    )
    ordering = [(item["occurred_at"], item["event_id"]) for item in first["items"]]
    assert ordering == sorted(ordering, reverse=True)
    filtered = api.get(
        "/api/v1/eoats/DEMO-P4-EOAT-0001/history",
        params={"event_category": "AUDITS", "event_type": "AUDIT_COMPLETED"},
    ).json()
    assert filtered["items"]
    assert all(item["event_category"] == "AUDITS" for item in filtered["items"])
    audit_id = filtered["items"][0]["metadata"]["audit_id"]
    searched = api.get("/api/v1/eoats/DEMO-P4-EOAT-0001/history", params={"search": audit_id}).json()
    assert searched["pagination"]["total"] == 1
    assert api.get("/api/v1/eoats/DOES-NOT-EXIST/history").status_code == 404


def test_search_fit_check_and_setup_packet(api):
    result = api.get("/api/v1/search", params={"q": "DEMO-P4-EOAT-0002"})
    assert result.status_code == 200
    assert any(item["category"] == "eoat" for item in result.json())
    profile = api.get("/api/v1/eoats/DEMO-P4-EOAT-0002").json()
    machine = next(item["identifier"] for item in profile["relationships"] if item["relationship_type"] == "machine")
    tool = next(item["identifier"] for item in profile["relationships"] if item["relationship_type"] == "tool")
    fit = api.post(
        "/api/v1/fit-checks/evaluate",
        json={"machine_number": machine, "tool_number": tool, "eoat_identifier": "DEMO-P4-EOAT-0002"},
    )
    assert fit.status_code == 200
    assert fit.json()["overall_result"] in {"COMPATIBLE", "NEEDS_REVIEW"}
    assert fit.json()["stored"] is False
    packet = api.get(
        "/api/v1/setup-packets/data",
        params={"machine_number": machine, "tool_number": tool, "eoat_identifier": "DEMO-P4-EOAT-0002"},
    )
    assert packet.status_code == 200
    assert packet.json()["source"] == "mysql_api"


def test_snapshot_cache_refresh_and_offline_read_only(api, tmp_path):
    cache = CacheRepository(tmp_path / "client.db")
    adapter = ApiClientAdapter(api)
    gateway = AtlasDataGateway(
        GatewayConfiguration(backend="mysql_api", cache_path=cache.path), client=adapter, cache=cache
    )
    deep = gateway.deep_refresh()
    assert deep["counts"]["eoats"] == 57
    assert gateway.refresh()["changes_applied"] == 0
    assert gateway.get_cache_status().entity_counts["photos"] == 2
    assert gateway.get_cache_status().entity_counts["eoat_history"] >= 1

    class Offline(ApiClientAdapter):
        def health(self):
            raise ApiUnavailableError("offline")

    offline = AtlasDataGateway(
        GatewayConfiguration(backend="mysql_api", cache_path=cache.path), client=Offline(api), cache=cache
    )
    assert offline.get_connection_status().mode == ConnectivityMode.OFFLINE_READ_ONLY
    assert offline.get_home_summary()["eoats"] == 57
    assert offline.search("DEMO-P4-EOAT")
    cached_history = offline.get_eoat_history("DEMO-P4-EOAT-0001")
    assert cached_history
    assert cached_history[0]["metadata"]["delivery_mode"] == "offline_cache"

    expected_ids = [item["event_id"] for item in cached_history]
    cache.path.unlink()
    gateway.deep_refresh()
    assert [item["event_id"] for item in cache.get_eoat_history("DEMO-P4-EOAT-0001")] == expected_ids


def test_version_incompatibility_blocks_refresh(api, tmp_path):
    gateway = AtlasDataGateway(
        GatewayConfiguration(
            backend="mysql_api", cache_path=tmp_path / "bad.db", expected_schema_revision="bad-revision"
        ),
        client=ApiClientAdapter(api),
    )
    assert gateway.get_connection_status().mode == ConnectivityMode.INCOMPATIBLE_SERVER
    with pytest.raises(IncompatibleServerError):
        gateway.deep_refresh()


def test_connectivity_recovers_after_timeout(api, tmp_path):
    adapter = ApiClientAdapter(api)

    class RecoveringClient(ApiClientAdapter):
        def __init__(self, client):
            super().__init__(client)
            self.calls = 0

        def health(self):
            self.calls += 1
            if self.calls == 1:
                raise ApiUnavailableError("simulated timeout")
            return adapter.health()

    gateway = AtlasDataGateway(
        GatewayConfiguration(backend="mysql_api", cache_path=tmp_path / "recover.db"),
        client=RecoveringClient(api),
    )
    assert gateway._status.mode == ConnectivityMode.OFFLINE_READ_ONLY
    assert gateway.get_connection_status().mode == ConnectivityMode.ONLINE


def test_import_traceability_and_safety():
    with create_session_factory()() as session:
        batch = session.scalar(
            select(db.ImportBatch).where(db.ImportBatch.status == "COMPLETED", db.ImportBatch.dry_run.is_(False))
        )
        assert batch is not None
        assert (
            session.scalar(select(func.count(db.ImportRow.id)).where(db.ImportRow.import_batch_id == batch.id)) == 0
        )
        assert (
            session.scalar(select(func.count(db.ImportIssue.id)).where(db.ImportIssue.import_batch_id == batch.id))
            == 1
        )
        assert session.scalar(select(func.count(db.Part.id))) == 0
        assert session.scalar(select(func.count(db.ToolPart.id))) == 0
        assert session.scalar(select(func.count(db.EOATInstallation.id))) == 1
        assert batch.source_file_name == "sanctioned_fixture.json"
        assert len(batch.source_file_checksum) == 64
        assert (
            session.scalar(
                select(func.count(db.ImportIssue.id)).where(
                    db.ImportIssue.import_batch_id == batch.id,
                    db.ImportIssue.issue_code == "SYNTHETIC_AMBIGUITY",
                )
            )
            == 1
        )


def test_desktop_gateway_contains_no_mysql_driver_or_credentials():
    source = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "core" / "data_gateway").glob("*.py"))
    assert "pymysql" not in source.casefold()
    assert "EOAT_DB_PASSWORD" not in source
    assert "DatabaseSettings" not in source


def test_mysql_api_workers_do_not_call_legacy_loader(monkeypatch):
    monkeypatch.setenv("EOAT_ATLAS_DATA_BACKEND", "mysql_api")
    import core.data_gateway as gateway_module
    from app.atlas.minimalist.window import MinimalistAtlasLoadWorker
    from core.atlas_models import AtlasDataBundle

    bundle = AtlasDataBundle(project_root="test", loaded_at="now", metrics={"backend": "mysql_api"})

    class FakeGateway:
        def __init__(self):
            self.cache = type("Cache", (), {"path": Path("exists")})()

        def deep_refresh(self):
            return {}

        def refresh(self):
            return {}

        def load_bundle(self, _root):
            return bundle

        def close(self):
            pass

    monkeypatch.setattr(gateway_module, "AtlasDataGateway", FakeGateway)
    monkeypatch.setattr(Path, "exists", lambda _self: True)
    import app.atlas.minimalist.window as minimalist

    assert not hasattr(minimalist, "load_atlas_data")
    minimalist_results = []
    second = MinimalistAtlasLoadWorker("test")
    second.finished.connect(minimalist_results.append)
    second.run()
    assert minimalist_results == [bundle]
