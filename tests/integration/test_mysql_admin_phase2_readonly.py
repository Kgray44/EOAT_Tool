from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from server.eoat_api.admin.repository import AuditEventRepository
from server.eoat_api.app import app
from server.eoat_api.database import models as db

TEST_URL = os.getenv("EOAT_MYSQL_TEST_URL")
RUNTIME_URL = os.getenv("EOAT_MYSQL_RUNTIME_URL")
RUN_TOKEN = uuid4().hex[:12]
VOLUME = 1_000
BASE_TIME = datetime(2026, 8, 11, 18, 0, tzinfo=timezone.utc)

pytestmark = pytest.mark.skipif(
    not TEST_URL or not RUNTIME_URL or os.getenv("EOAT_DB_NAME") != "eoat_atlas_test",
    reason="Phase 2 real-MySQL acceptance requires the isolated eoat_atlas_test environment",
)


@pytest.fixture(scope="module")
def migration_engine():
    engine = create_engine(TEST_URL, pool_pre_ping=True)
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def accepted_events(migration_engine):
    older_tied_id = f"ffffffff-ffff-4fff-8fff-{RUN_TOKEN}"
    newer_tied_id = f"00000000-0000-4000-8000-{RUN_TOKEN}"
    common = {
        "actor_type": "user",
        "actor_id": "phase2-admin",
        "actor_display_name": "Phase 2 Administrator",
        "actor_directory_name": "dev.admin",
        "entity_type": "EOAT",
        "entity_id": "phase2-eoat-54",
        "entity_display_id": f"PHASE2-{RUN_TOKEN}",
        "changed_fields_json": ["location", "password"],
        "before_state_json": {"location": "Synthetic storage", "password": {"_audit_value": "REDACTED"}},
        "after_state_json": {"location": "Synthetic cell", "password": {"_audit_value": "REDACTED"}},
        "reason_or_note": "Synthetic Phase 2 acceptance evidence",
        "request_id": f"phase2-request-{RUN_TOKEN}",
        "correlation_id": f"phase2-correlation-{RUN_TOKEN}",
        "transaction_id": f"phase2-transaction-{RUN_TOKEN}",
        "operation": "PATCH /api/v1/eoats/phase2-eoat-54",
        "schema_version": 1,
    }
    rows = [
        {
            **common,
            "event_id": older_tied_id,
            "occurred_at_utc": BASE_TIME,
            "action": "UPDATE",
            "action_category": "BUSINESS_DATA",
            "source_client": "web",
            "result": "SUCCESS",
        },
        {
            **common,
            "event_id": newer_tied_id,
            "occurred_at_utc": BASE_TIME,
            "action": "ADMIN_REPAIR",
            "action_category": "SYSTEM_OPERATIONS",
            "source_client": "api",
            "result": "DENIED",
        },
    ]
    for index in range(VOLUME):
        action, category = (
            ("LOCATION_CHANGE", "LOCATION_STATE")
            if index % 5 == 0
            else ("UPDATE", "BUSINESS_DATA")
        )
        rows.append(
            {
                **common,
                "event_id": f"phase2-{RUN_TOKEN}-{index:04d}",
                "occurred_at_utc": BASE_TIME - timedelta(seconds=index + 1),
                "actor_id": "phase2-actor" if index % 2 else "phase2-admin",
                "actor_display_name": "Phase 2 Actor" if index % 2 else "Phase 2 Administrator",
                "actor_directory_name": "dev.actor" if index % 2 else "dev.admin",
                "entity_type": "Tool" if index % 3 == 0 else "EOAT",
                "entity_id": f"phase2-entity-{index % 17}",
                "entity_display_id": f"PHASE2-{RUN_TOKEN}-{index % 17}",
                "action": action,
                "action_category": category,
                "source_client": "scheduled_service" if index % 7 == 0 else "web",
                "result": "FAILURE" if index % 11 == 0 else "SUCCESS",
            }
        )
    with migration_engine.begin() as connection:
        connection.execute(db.AuditEvent.__table__.insert(), rows)
    return {
        "correlation_id": common["correlation_id"],
        "request_id": common["request_id"],
        "newer_tied_id": newer_tied_id,
        "older_tied_id": older_tied_id,
        "total": len(rows),
    }


@pytest.fixture(scope="module")
def api():
    with TestClient(app) as client:
        yield client


ADMIN = {"X-EOAT-Identity": "dev.admin"}
VIEWER = {"X-EOAT-Identity": "dev.viewer"}


def _page(api: TestClient, accepted_events: dict[str, str | int], **params):
    response = api.get(
        "/api/v1/admin/audit/events",
        params={"correlation_id": accepted_events["correlation_id"], **params},
        headers=ADMIN,
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_real_mysql_admin_authorization_and_schema_boundary(api, accepted_events):
    assert api.get("/api/v1/admin/audit/events").status_code == 401
    assert api.get("/api/v1/admin/audit/events", headers=VIEWER).status_code == 403
    catalog = api.get("/api/v1/admin/audit/catalog", headers=ADMIN)
    assert catalog.status_code == 200
    assert "EOAT" in catalog.json()["entity_types"]
    assert _page(api, accepted_events, page_size=1)["total"] == accepted_events["total"]


def test_real_mysql_ledger_filters_pagination_and_persisted_tie_order(api, accepted_events):
    first = _page(api, accepted_events, page=1, page_size=100)
    second = _page(api, accepted_events, page=2, page_size=100)
    assert first["sort"] == "occurred_at_utc:desc,persisted_sequence:desc"
    assert first["items"][0]["event_id"] == accepted_events["newer_tied_id"]
    assert first["items"][1]["event_id"] == accepted_events["older_tied_id"]
    assert len(first["items"]) == len(second["items"]) == 100
    assert {item["event_id"] for item in first["items"]}.isdisjoint(item["event_id"] for item in second["items"])

    collected = []
    for page in range(1, 12):
        collected.extend(item["event_id"] for item in _page(api, accepted_events, page=page, page_size=100)["items"])
    assert len(collected) == len(set(collected)) == accepted_events["total"]

    assert _page(api, accepted_events, start="2026-08-11T17:59:55Z")["total"] == 7
    assert _page(api, accepted_events, actor="dev.actor")["total"] == VOLUME // 2
    assert _page(api, accepted_events, action="LOCATION_CHANGE")["total"] == VOLUME // 5
    assert _page(api, accepted_events, administrative_events_only="true")["total"] == 1
    assert _page(api, accepted_events, entity_type="Tool")["total"] == 334
    assert _page(api, accepted_events, entity_id="phase2-entity-1")["total"] == 59
    assert _page(api, accepted_events, result="DENIED")["total"] == 1
    assert _page(api, accepted_events, source="scheduled_service")["total"] == 143
    assert _page(api, accepted_events, request_id=accepted_events["request_id"])["total"] == accepted_events["total"]
    assert _page(api, accepted_events, search=RUN_TOKEN)["total"] == accepted_events["total"]


def test_real_mysql_event_detail_correlation_redaction_and_bounded_query_count(migration_engine, api, accepted_events):
    detail = api.get(f"/api/v1/admin/audit/events/{accepted_events['newer_tied_id']}", headers=ADMIN)
    assert detail.status_code == 200
    body = detail.json()
    assert body["actor"]["directory_name"] == "dev.admin"
    assert body["entity"]["id"] == "phase2-eoat-54"
    assert body["occurred_at_utc"].startswith("2026-08-11T18:00:00")
    assert body["before"]["password"] == {"_audit_value": "REDACTED"}
    assert body["after"]["password"] == {"_audit_value": "REDACTED"}
    assert body["request_id"] == accepted_events["request_id"]
    assert body["correlation_id"] == accepted_events["correlation_id"]

    selects = 0

    def count_selects(_connection, _cursor, statement, _parameters, _context, _executemany):
        nonlocal selects
        if statement.lstrip().upper().startswith("SELECT"):
            selects += 1

    event.listen(migration_engine, "before_cursor_execute", count_selects)
    try:
        with Session(migration_engine) as session:
            started = time.monotonic()
            rows, total = AuditEventRepository(session).list(
                page=3,
                page_size=100,
                correlation_id=accepted_events["correlation_id"],
            )
            elapsed = time.monotonic() - started
    finally:
        event.remove(migration_engine, "before_cursor_execute", count_selects)
    assert total == accepted_events["total"]
    assert len(rows) == 100
    assert selects == 2
    assert elapsed < 10
