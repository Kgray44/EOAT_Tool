from __future__ import annotations

import json
import os

import httpx
import pytest

from app.atlas.minimalist.data import data_source_status_text
from core.data_gateway.api_client import AtlasApiClient
from core.data_gateway.cache_repository import CacheRepository
from core.data_gateway.configuration import GatewayConfiguration, configure_packaged_production_environment
from core.data_gateway.exceptions import ApiUnavailableError, IncompatibleServerError, WriteBlockedError
from core.data_gateway.gateway import AtlasDataGateway


class OfflineClient:
    def health(self):
        raise ApiUnavailableError("production endpoint is unavailable")


class IncompatibleClient:
    def health(self):
        return {
            "api_reachable": True,
            "database_reachable": True,
            "api_version": "9.9.9",
            "current_schema_revision": "wrong-schema",
            "compatible": False,
        }


def _snapshot() -> dict:
    return {
        "api_version": "1.4.0",
        "schema_revision": "20260717_0007",
        "server_revision": "production-test",
        "eoats": [{"business_identifier": "P4-EOAT-0001"}],
        "machines": [{"plant_code": "P4", "machine_number": "1"}],
        "tools": [{"business_identifier": "TOOL-1"}],
        "photos": [],
        "documents": [],
        "lookups": {},
        "eoat_history": [],
    }


def test_packaged_profile_forces_the_production_endpoint_and_read_only_cache(tmp_path, monkeypatch) -> None:
    profile = tmp_path / "production.json"
    profile.write_text(
        json.dumps(
            {
                "environment": "production",
                "backend": "mysql_api",
                "api_url": "http://eoat-atlas.gwplastics.com/api/v1",
                "writes_enabled": False,
                "expected_api_version": "1.4.0",
                "expected_schema_revision": "20260717_0007",
                "cache_filename": "eoat_atlas_api_cache.db",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EOAT_ATLAS_LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("EOAT_ATLAS_API_URL", "http://127.0.0.1:8765")
    monkeypatch.setenv("EOAT_ATLAS_WRITES_ENABLED", "true")
    monkeypatch.setenv("EOAT_ATLAS_DEV_IDENTITY", "dev.admin")

    configure_packaged_production_environment(profile)
    configuration = GatewayConfiguration.from_environment()

    assert configuration.api_base_url == "http://eoat-atlas.gwplastics.com/api/v1"
    assert configuration.environment == "production"
    assert configuration.writes_enabled is False
    assert configuration.expected_api_version == "1.4.0"
    assert configuration.expected_schema_revision == "20260717_0007"
    assert configuration.development_identity == ""
    assert configuration.cache_path.name == "eoat_atlas_api_cache.db"
    assert "EOAT_Atlas" in configuration.cache_path.parts
    for key in (
        "EOAT_ATLAS_DATA_BACKEND",
        "EOAT_ATLAS_ENVIRONMENT",
        "EOAT_ATLAS_EXPECTED_API_VERSION",
        "EOAT_ATLAS_EXPECTED_SCHEMA_REVISION",
        "EOAT_ATLAS_RUNTIME_FOLDER_NAME",
        "EOAT_ATLAS_API_CACHE",
    ):
        os.environ.pop(key, None)


def test_offline_bundle_is_explicitly_marked_as_cached_and_writes_are_blocked(tmp_path) -> None:
    cache = CacheRepository(tmp_path / "production-cache.db")
    cache.build_snapshot(_snapshot(), cache.path)
    configuration = GatewayConfiguration(
        backend="mysql_api",
        cache_path=cache.path,
        environment="production",
        writes_enabled=False,
    )
    gateway = AtlasDataGateway(configuration, client=OfflineClient(), cache=cache)

    bundle = gateway.load_bundle("test")

    assert bundle.metrics["data_source_status"] == "Using cached data"
    assert "Using cached data" in data_source_status_text(bundle)
    assert bundle.metrics["last_successful_server_refresh"]
    with pytest.raises(WriteBlockedError, match="no server edit was saved"):
        gateway.create_eoat({"business_identifier": "DO-NOT-WRITE"})


def test_api_client_accepts_the_authoritative_v1_endpoint_url() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return httpx.Response(200, json={"api_reachable": True, "database_reachable": True})

    client = AtlasApiClient(
        "http://eoat-atlas.gwplastics.com/api/v1",
        transport=httpx.MockTransport(handler),
    )
    try:
        assert client.health()["api_reachable"] is True
    finally:
        client.close()

    assert paths == ["/api/v1/health"]


def test_incompatible_server_fails_closed_instead_of_serving_the_cached_bundle(tmp_path) -> None:
    cache = CacheRepository(tmp_path / "production-cache.db")
    cache.build_snapshot(_snapshot(), cache.path)
    configuration = GatewayConfiguration(
        backend="mysql_api",
        cache_path=cache.path,
        environment="production",
        writes_enabled=False,
    )
    gateway = AtlasDataGateway(configuration, client=IncompatibleClient(), cache=cache)

    status = gateway.data_source_status()
    assert status["state"] == "Server unavailable"
    assert status["using_cached_data"] is False
    assert "cached data is not used" in status["detail"]
    with pytest.raises(IncompatibleServerError):
        gateway.load_bundle("test")
