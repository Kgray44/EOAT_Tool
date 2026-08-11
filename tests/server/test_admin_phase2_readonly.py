from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from server.eoat_api.admin.repository import AuditEventRepository
from server.eoat_api.app import app
from server.eoat_api.database import models as db
from server.eoat_api.database.session import get_runtime_session
from server.eoat_api.errors import APIError
from server.eoat_api.security import ActorContext, read_actor_context

NOW = datetime(2026, 8, 11, 18, 0, tzinfo=timezone.utc)


def audit_event(
    event_id: str,
    occurred_at: datetime,
    *,
    result: str = "SUCCESS",
    category: str = "BUSINESS_DATA",
    actor: str = "42",
    record_id: int | None = None,
):
    return db.AuditEvent(
        id=record_id if record_id is not None else sum(ord(character) for character in event_id),
        event_id=event_id,
        occurred_at_utc=occurred_at,
        actor_type="user",
        actor_id=actor,
        actor_display_name=f"Actor {actor}",
        actor_directory_name=f"actor.{actor}",
        action="UPDATE",
        action_category=category,
        entity_type="EOAT",
        entity_id="54",
        entity_display_id="CL-EOAT-0054",
        changed_fields_json=["status"],
        before_state_json={"status": "Available"},
        after_state_json={"status": "Installed"},
        source_client="web",
        result=result,
        schema_version=1,
        created_at=occurred_at,
    )


def test_overview_metrics_are_ledger_derived_and_utc_bounded():
    engine = create_engine("sqlite://")
    db.AuditEvent.__table__.create(engine)
    try:
        with Session(engine) as session:
            session.add_all(
                [
                    audit_event("event-1", NOW - timedelta(minutes=5)),
                    audit_event("event-2", NOW - timedelta(hours=2), result="DENIED", category="AUTHORIZATION", actor="77"),
                    audit_event("event-3", NOW - timedelta(hours=3), result="FAILURE", category="AUTHENTICATION"),
                    audit_event("event-4", NOW - timedelta(hours=26)),
                ]
            )
            session.commit()
            metrics, recent = AuditEventRepository(session).overview(now=NOW)
    finally:
        engine.dispose()

    assert metrics == {
        "events_today": 3,
        "events_last_24_hours": 3,
        "successful_events_last_24_hours": 1,
        "failed_events_last_24_hours": 1,
        "denied_events_last_24_hours": 1,
        "security_events_last_24_hours": 2,
        "administrative_events_last_24_hours": 0,
        "unique_actors_last_24_hours": 2,
    }
    assert [event.event_id for event in recent] == ["event-1", "event-2", "event-3", "event-4"]


def test_overview_recent_events_use_the_governed_tied_timestamp_order():
    engine = create_engine("sqlite://")
    db.AuditEvent.__table__.create(engine)
    try:
        with Session(engine) as session:
            session.add_all(
                [
                    audit_event("event-z", NOW, record_id=10),
                    audit_event("event-a", NOW, record_id=20),
                ]
            )
            session.commit()
            _, recent = AuditEventRepository(session).overview(now=NOW)
    finally:
        engine.dispose()

    assert [event.event_id for event in recent] == ["event-a", "event-z"]


def test_catalog_keeps_authorization_server_side_for_anonymous_viewer_and_admin():
    def anonymous():
        raise APIError(401, "UNKNOWN_IDENTITY", "A configured local identity is required.")

    def viewer():
        return ActorContext(0, "dev.viewer", "Viewer", "VIEWER", "request-viewer", None, None)

    def administrator():
        return ActorContext(1, "dev.admin", "Administrator", "ADMINISTRATOR", "request-admin", None, None)

    try:
        with TestClient(app) as client:
            app.dependency_overrides[read_actor_context] = anonymous
            assert client.get("/api/v1/admin/audit/catalog").status_code == 401
            app.dependency_overrides[read_actor_context] = viewer
            assert client.get("/api/v1/admin/audit/catalog").status_code == 403
            app.dependency_overrides[read_actor_context] = administrator
            response = client.get("/api/v1/admin/audit/catalog")
            assert response.status_code == 200
            assert "UPDATE" in response.json()["actions"]
    finally:
        app.dependency_overrides.clear()


def test_audit_api_uses_server_filters_pagination_and_controlled_failures():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    db.AuditEvent.__table__.create(engine)

    def administrator():
        return ActorContext(1, "dev.admin", "Administrator", "ADMINISTRATOR", "request-admin", None, None)

    try:
        with Session(engine) as session:
            latest = audit_event("event-3", NOW, category="SYSTEM_OPERATIONS")
            latest.actor_directory_name = "dev.admin"
            latest.request_id = "request-searchable"
            latest.correlation_id = "correlation-1"
            latest.reason_or_note = "approved synthetic administrative operation"
            earlier = audit_event("event-2", NOW - timedelta(minutes=1), actor="77")
            earliest = audit_event("event-1", NOW - timedelta(minutes=2), result="DENIED", category="AUTHORIZATION")
            session.add_all([latest, earlier, earliest])
            session.commit()

            def session_override():
                yield session

            app.dependency_overrides[get_runtime_session] = session_override
            app.dependency_overrides[read_actor_context] = administrator
            with TestClient(app) as client:
                first_page = client.get("/api/v1/admin/audit/events?page=1&page_size=1")
                second_page = client.get("/api/v1/admin/audit/events?page=2&page_size=1")
                assert first_page.status_code == second_page.status_code == 200
                assert first_page.json()["items"][0]["event_id"] == "event-3"
                assert second_page.json()["items"][0]["event_id"] == "event-2"
                assert client.get("/api/v1/admin/audit/events?current_user_changes=true").json()["total"] == 1
                assert client.get("/api/v1/admin/audit/events?administrative_events_only=true").json()["total"] == 1
                assert client.get("/api/v1/admin/audit/events?search=request-searchable").json()["total"] == 1
                assert client.get("/api/v1/admin/audit/events?correlation_id=correlation-1").json()["total"] == 1
                assert client.get("/api/v1/admin/audit/events?start=2026-08-11T17:59:30Z").json()["total"] == 1
                assert client.get("/api/v1/admin/audit/events?action=NOT_A_REAL_ACTION").status_code == 422
                assert client.get("/api/v1/admin/audit/events/not-recorded").status_code == 404
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_audit_repository_applies_every_safe_query_dimension():
    engine = create_engine("sqlite://")
    db.AuditEvent.__table__.create(engine)
    try:
        with Session(engine) as session:
            administrative = audit_event("event-admin", NOW, category="SYSTEM_OPERATIONS", actor="admin", record_id=10)
            administrative.action = "ADMIN_REPAIR"
            administrative.entity_type = "Machine"
            administrative.entity_id = "machine-27"
            administrative.entity_display_id = "TEST-MACHINE-27"
            administrative.source_client = "system"
            administrative.request_id = "request-admin"
            administrative.correlation_id = "correlation-admin"
            administrative.reason_or_note = "Synthetic repair evidence"
            security = audit_event("event-security", NOW - timedelta(minutes=1), result="DENIED", category="AUTHENTICATION", actor="security", record_id=11)
            security.action = "LOGIN_FAILURE"
            security.source_client = "api"
            ordinary = audit_event("event-ordinary", NOW - timedelta(minutes=2), actor="ordinary", record_id=12)
            session.add_all([administrative, security, ordinary])
            session.commit()
            repository = AuditEventRepository(session)

            def event_ids(**filters):
                rows, total = repository.list(page=1, page_size=50, **filters)
                assert total == len(rows)
                return [row.event_id for row in rows]

            assert event_ids(start=NOW - timedelta(seconds=1)) == ["event-admin"]
            assert event_ids(end=NOW - timedelta(seconds=30)) == ["event-security", "event-ordinary"]
            assert event_ids(actor="admin") == ["event-admin"]
            assert event_ids(action="ADMIN_REPAIR") == ["event-admin"]
            assert event_ids(action_category="AUTHENTICATION") == ["event-security"]
            assert event_ids(entity_type="Machine") == ["event-admin"]
            assert event_ids(entity_id="machine-27") == ["event-admin"]
            assert event_ids(result="DENIED") == ["event-security"]
            assert event_ids(source="system") == ["event-admin"]
            assert event_ids(request_id="request-admin") == ["event-admin"]
            assert event_ids(correlation_id="correlation-admin") == ["event-admin"]
            assert event_ids(search="Synthetic repair") == ["event-admin"]
            assert event_ids(security_events_only=True) == ["event-security"]
            assert event_ids(administrative_events_only=True) == ["event-admin"]
    finally:
        engine.dispose()


def test_large_synthetic_ledger_page_is_bounded_and_deterministically_ordered():
    engine = create_engine("sqlite://")
    db.AuditEvent.__table__.create(engine)
    try:
        with Session(engine) as session:
            session.add_all(
                audit_event(
                    f"volume-{index:04d}",
                    NOW - timedelta(seconds=index),
                    record_id=10_000 + index,
                )
                for index in range(1_000)
            )
            session.commit()
            first, total = AuditEventRepository(session).list(page=1, page_size=100)
            second, _ = AuditEventRepository(session).list(page=2, page_size=100)
    finally:
        engine.dispose()

    assert total == 1_000
    assert len(first) == len(second) == 100
    assert first[0].event_id == "volume-0000"
    assert set(event.event_id for event in first).isdisjoint(event.event_id for event in second)
