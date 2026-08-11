from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from server.eoat_api.admin.repository import AuditEventRepository
from server.eoat_api.app import app
from server.eoat_api.database import models as db
from server.eoat_api.errors import APIError
from server.eoat_api.security import ActorContext, read_actor_context

NOW = datetime(2026, 8, 11, 18, 0, tzinfo=timezone.utc)


def audit_event(event_id: str, occurred_at: datetime, *, result: str = "SUCCESS", category: str = "BUSINESS_DATA", actor: str = "42"):
    return db.AuditEvent(
        id=sum(ord(character) for character in event_id),
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
            session.add_all([audit_event("event-a", NOW), audit_event("event-z", NOW)])
            session.commit()
            _, recent = AuditEventRepository(session).overview(now=NOW)
    finally:
        engine.dispose()

    assert [event.event_id for event in recent] == ["event-z", "event-a"]


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
