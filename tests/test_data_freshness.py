from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.atlas.minimalist.data import loaded_status_text
from app.atlas.minimalist.settings_store import get_default_settings, validate_settings_schema
from core.data_freshness import (
    DataFreshnessService,
    FreshnessProtocolError,
    FreshnessSettings,
    PollingState,
    format_relative_timestamp,
)
from server.eoat_api.app import app
from server.eoat_api.app import service as service_dependency
from server.eoat_api.data_state import mark_data_changed, record_import_completion
from server.eoat_api.database import models as db
from server.eoat_api.services import AtlasService


def _payload(revision: int, modified: str = "2026-07-21T14:18:43.128Z") -> dict:
    return {
        "status": "available",
        "data_revision": revision,
        "data_last_modified_at": modified,
        "last_import_at": "2026-07-21T12:42:11.002Z",
        "last_import_source": "test-import",
        "server_time": "2026-07-21T14:19:02.415Z",
        "source": "mysql",
        "environment": "test",
    }


def test_same_revision_only_updates_last_checked_and_never_data_modified_time() -> None:
    now = datetime(2026, 7, 21, 14, 19, 5, tzinfo=timezone.utc)
    service = DataFreshnessService(now=lambda: now)
    service.begin_check()
    service.receive_status(_payload(7), received_at=now)
    original = service.data_last_modified_at
    first_checked = service.last_checked_at

    later = now + timedelta(minutes=5)
    service.begin_check()
    transition = service.receive_status(_payload(7, "2026-07-21T14:19:00.000Z"), received_at=later)

    assert transition.kind == "unchanged"
    assert service.data_last_modified_at == original
    assert service.last_checked_at == later
    assert service.last_checked_at != first_checked


def test_first_status_after_snapshot_revision_adopts_missing_authoritative_timestamp() -> None:
    now = datetime(2026, 7, 21, 14, 19, 5, tzinfo=timezone.utc)
    service = DataFreshnessService(now=lambda: now, current_revision=7)
    service.begin_check()

    transition = service.receive_status(_payload(7), received_at=now)

    assert transition.kind == "unchanged"
    assert service.data_last_modified_at == datetime(2026, 7, 21, 14, 18, 43, 128000, tzinfo=timezone.utc)


def test_new_and_decreased_revisions_mark_displayed_pages_stale() -> None:
    now = datetime(2026, 7, 21, 14, 19, tzinfo=timezone.utc)
    service = DataFreshnessService(now=lambda: now)
    service.begin_check()
    service.receive_status(_payload(4), received_at=now)
    service.mark_page_applied("fit_check", revision=4)
    service.begin_check()
    advanced = service.receive_status(_payload(5), received_at=now + timedelta(seconds=60))
    assert advanced.refresh_required
    assert service.pages["fit_check"].stale
    assert service.state == PollingState.UPDATE_AVAILABLE

    service.begin_check()
    decreased = service.receive_status(_payload(2), received_at=now + timedelta(seconds=120))
    assert decreased.kind == "decreased"
    assert decreased.warning
    assert service.pages["fit_check"].stale


def test_failure_backoff_is_bounded_and_manual_check_is_allowed_when_polling_disabled() -> None:
    service = DataFreshnessService(settings=FreshnessSettings(automatic_polling_enabled=False))
    assert not service.begin_check()
    assert service.begin_check(manual=True)
    for _ in range(8):
        service.record_failure("offline")
    assert service.retry_delay_seconds == 300
    assert service.state == PollingState.ERROR


def test_primary_status_labels_distinguish_unknown_manual_failure_and_deferred_refresh() -> None:
    service = DataFreshnessService()
    assert service.primary_text() == "Data freshness unknown"

    service.begin_check()
    service.record_failure("offline")
    assert service.primary_text() == "Could not check for updates"

    service = DataFreshnessService(settings=FreshnessSettings(automatic_polling_enabled=False))
    service.configure(service.settings)
    assert service.primary_text() == "Manual updates enabled"
    service.begin_check(manual=True)
    service.receive_status(_payload(4))
    assert service.state == PollingState.DISABLED
    assert service.primary_text() == "Manual updates enabled"

    now = datetime(2026, 7, 21, 14, 19, tzinfo=timezone.utc)
    service = DataFreshnessService(now=lambda: now)
    service.begin_check()
    service.receive_status(_payload(4), received_at=now)
    service.mark_page_applied("settings", revision=4)
    service.begin_check()
    service.receive_status(_payload(5), received_at=now + timedelta(seconds=15))
    service.mark_refresh_deferred("editing")
    assert service.primary_text() == "Update available · Refresh paused while editing"
    service.mark_refresh_deferred("operation")
    assert service.primary_text() == "Update available · Refresh paused while an operation is in progress"


def test_invalid_protocol_never_manufactures_a_revision() -> None:
    service = DataFreshnessService()
    service.begin_check()
    invalid = _payload(1)
    invalid["data_revision"] = "1"
    with pytest.raises(FreshnessProtocolError):
        service.receive_status(invalid)
    assert service.current_revision is None


@pytest.mark.parametrize(
    ("offset_seconds", "expected"),
    ((0, "just now"), (60, "1 minute ago"), (120, "2 minutes ago")),
)
def test_relative_timestamp_boundaries(offset_seconds: int, expected: str) -> None:
    timestamp = datetime(2026, 7, 21, 14, 0, tzinfo=timezone.utc)
    assert format_relative_timestamp(timestamp, now=timestamp + timedelta(seconds=offset_seconds)) == expected


def test_status_text_refuses_to_call_a_bundle_load_a_data_update() -> None:
    bundle = SimpleNamespace(loaded_at="2026-07-21T14:19:00Z", metrics={})
    assert loaded_status_text(bundle) == "Data update time unavailable"
    bundle.metrics["freshness_primary_text"] = "Data last updated 4 minutes ago"
    assert loaded_status_text(bundle) == "Data last updated 4 minutes ago"


def test_polling_settings_defaults_and_invalid_values_are_migrated() -> None:
    settings = get_default_settings()
    data_loading = settings["data_loading"]
    assert FreshnessSettings.from_mapping(data_loading).polling_interval_seconds == 60
    data_loading["polling_interval_seconds"] = 999
    data_loading["refresh_when_data_changes"] = "bad"
    normalized = validate_settings_schema(settings)["data_loading"]
    assert normalized["polling_interval_seconds"] == 60
    assert normalized["refresh_when_data_changes"] == "notify"


@pytest.fixture()
def data_state_session():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    db.DataState.__table__.create(engine)
    factory = sessionmaker(bind=engine, future=True)
    with factory() as session:
        session.add(
            db.DataState(id=1, current_revision=0, data_last_modified_at=datetime(2026, 7, 21, tzinfo=timezone.utc))
        )
        session.commit()
        yield session


def test_data_state_advances_once_per_committed_transaction(data_state_session) -> None:
    mark_data_changed(data_state_session)
    mark_data_changed(data_state_session)
    data_state_session.commit()
    assert data_state_session.get(db.DataState, 1).current_revision == 1


def test_data_state_does_not_advance_on_rollback(data_state_session) -> None:
    mark_data_changed(data_state_session)
    data_state_session.rollback()
    assert data_state_session.get(db.DataState, 1).current_revision == 0


def test_import_metadata_only_advances_revision_when_material(data_state_session) -> None:
    record_import_completion(data_state_session, source="no-op.xlsx", changed_data=False)
    data_state_session.commit()
    state = data_state_session.get(db.DataState, 1)
    assert state.current_revision == 0
    assert state.last_import_source == "no-op.xlsx"
    record_import_completion(data_state_session, source="changed.xlsx", changed_data=True)
    data_state_session.commit()
    state = data_state_session.get(db.DataState, 1)
    assert state.current_revision == 1
    assert state.last_import_source == "changed.xlsx"


def test_service_data_status_is_compact_and_authoritative(data_state_session) -> None:
    state = data_state_session.get(db.DataState, 1)
    state.current_revision = 12
    data_state_session.commit()
    payload = AtlasService(data_state_session).data_status()
    assert payload.status == "available"
    assert payload.data_revision == 12
    assert payload.source == "mysql"


def test_data_status_endpoint_is_anonymous_read_and_uses_the_standard_payload() -> None:
    payload = _payload(12)
    app.dependency_overrides[service_dependency] = lambda: SimpleNamespace(data_status=lambda: payload)
    try:
        response = TestClient(app).get("/api/v1/data-status")
    finally:
        app.dependency_overrides.pop(service_dependency, None)
    assert response.status_code == 200
    assert response.json()["data_revision"] == 12
    assert set(response.json()) == {
        "status",
        "data_revision",
        "data_last_modified_at",
        "last_import_at",
        "last_import_source",
        "server_time",
        "source",
        "environment",
    }
