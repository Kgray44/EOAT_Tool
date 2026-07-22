from __future__ import annotations

from datetime import datetime, timezone

from core.data_gateway.cache_repository import CacheRepository
from core.data_gateway.configuration import GatewayConfiguration
from core.data_gateway.exceptions import ApiUnavailableError
from core.data_gateway.gateway import AtlasDataGateway
from core.eoat_history import EOATHistoryService, GatewayEOATHistoryRepository


def _event(identifier: str = "EOAT-1", event_id: str = "event-1") -> dict:
    return {
        "event_id": event_id,
        "eoat_identifier": identifier,
        "event_type": "EOAT_UPDATED",
        "event_category": "ENGINEERING_CHANGES",
        "occurred_at": "2026-07-14T12:00:00Z",
        "summary": "EOAT updated",
        "description": "Connection type corrected",
        "actor": "Test Engineer",
        "source_record_type": "eoats",
        "source_record_id": "1",
        "previous_values": {"connection_type": "A"},
        "new_values": {"connection_type": "B"},
        "metadata": {},
    }


class OnlineClient:
    def __init__(self, events: list[dict]):
        self.events = events
        self.history_calls = 0

    def health(self):
        return {
            "api_version": "1.4.0",
            "current_schema_revision": "20260721_0008",
            "compatible": True,
        }

    def get_eoat_history(self, identifier, **params):
        self.history_calls += 1
        page = int(params.get("page", 1))
        return {
            "items": self.events if page == 1 else [],
            "pagination": {"page": page, "page_size": 200, "total": len(self.events), "pages": 1},
        }

    def close(self):
        pass


class OfflineClient(OnlineClient):
    def health(self):
        raise ApiUnavailableError("offline")


def test_gateway_history_is_api_backed_then_available_from_disposable_cache(tmp_path) -> None:
    cache = CacheRepository(tmp_path / "history-cache.db")
    config = GatewayConfiguration(backend="mysql_api", cache_path=cache.path)
    online_client = OnlineClient([_event()])
    online = AtlasDataGateway(config, client=online_client, cache=cache)
    assert online.get_eoat_history("EOAT-1")[0]["event_id"] == "event-1"
    assert online_client.history_calls == 1

    offline = AtlasDataGateway(config, client=OfflineClient([]), cache=cache)
    cached = offline.get_eoat_history("EOAT-1")
    assert cached[0]["event_id"] == "event-1"
    assert cached[0]["metadata"]["delivery_mode"] == "offline_cache"


def test_cache_rebuild_restores_history_from_snapshot(tmp_path) -> None:
    path = tmp_path / "rebuilt.db"
    cache = CacheRepository(path)
    snapshot = {
        "api_version": "1.4.0",
        "schema_revision": "20260721_0008",
        "server_revision": "test",
        "cursor": 4,
        "eoats": [{"business_identifier": "EOAT-1"}],
        "machines": [{"machine_number": "M-1"}],
        "tools": [{"business_identifier": "T-1"}],
        "documents": [],
        "photos": [],
        "lookups": {},
        "eoat_history": [_event()],
    }
    cache.build_snapshot(snapshot, path)
    assert cache.validate()["eoat_history"] == 1
    assert cache.get_eoat_history("EOAT-1")[0]["event_id"] == "event-1"


def test_typed_history_mapping_preserves_event_type_category_and_changes(monkeypatch) -> None:
    class FakeGateway:
        def get_eoat_history(self, identifier):
            return [_event(identifier)]

        def close(self):
            pass

    import core.data_gateway as gateway_module

    monkeypatch.setattr(gateway_module, "AtlasDataGateway", FakeGateway)
    view = EOATHistoryService(GatewayEOATHistoryRepository()).history_for("EOAT-1")
    event = view.events[0]
    assert event.event_type == "EOAT_UPDATED"
    assert event.event_category == "ENGINEERING_CHANGES"
    assert event.recorded_by == "Test Engineer"
    assert event.previous_values == {"connection_type": "A"}
    assert event.new_values == {"connection_type": "B"}
    assert event.effective_timestamp == datetime(2026, 7, 14, 12, tzinfo=timezone.utc)
