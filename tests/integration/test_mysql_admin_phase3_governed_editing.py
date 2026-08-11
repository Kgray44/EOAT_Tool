from __future__ import annotations

import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from server.eoat_api.app import app
from server.eoat_api.database import models as db
from server.eoat_api.database.session import create_session_factory


pytestmark = pytest.mark.skipif(
    os.getenv("EOAT_DB_NAME") != "eoat_atlas_test",
    reason="Phase 3 governed-editing integration tests require EOAT_DB_NAME=eoat_atlas_test",
)

RUN = uuid4().hex[:10]
REHEARSAL_SECRET = "phase3-integration-rehearsal-secret"


@pytest.fixture(scope="module", autouse=True)
def phase3_environment():
    previous_writes = os.environ.get("EOAT_API_WRITES_ENABLED")
    previous_environment = os.environ.get("EOAT_API_ENVIRONMENT")
    previous_secret = os.environ.get("EOAT_API_ADMIN_REHEARSAL_SECRET")
    os.environ["EOAT_API_WRITES_ENABLED"] = "true"
    os.environ["EOAT_API_ENVIRONMENT"] = "development"
    os.environ["EOAT_API_ADMIN_REHEARSAL_SECRET"] = REHEARSAL_SECRET
    yield
    for key, value in {
        "EOAT_API_WRITES_ENABLED": previous_writes,
        "EOAT_API_ENVIRONMENT": previous_environment,
        "EOAT_API_ADMIN_REHEARSAL_SECRET": previous_secret,
    }.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


@pytest.fixture(scope="module")
def seed_records():
    factory = create_session_factory(migration=True)
    identifiers = [f"P3-{RUN}-A", f"P3-{RUN}-B"]
    setting_key = f"phase3.{RUN}.enabled"
    secret_setting_key = f"phase3.{RUN}.secret"
    with factory() as session, session.begin():
        for identifier in identifiers:
            session.add(db.EOAT(business_identifier=identifier, display_name="Phase 3 before", source_system="integration_test"))
        session.add(
            db.SystemSetting(
                setting_key=setting_key,
                setting_value_json=False,
                value_type="boolean",
                description="Phase 3 isolated integration setting",
                is_sensitive=False,
                source_system="integration_test",
            )
        )
        session.add(
            db.SystemSetting(
                setting_key=secret_setting_key,
                setting_value_json="configured-before-test",
                value_type="string",
                description="Phase 3 isolated secret setting",
                is_sensitive=True,
                source_system="integration_test",
            )
        )
    return identifiers, setting_key, secret_setting_key


@pytest.fixture
def api():
    with TestClient(app, raise_server_exceptions=False) as client:
        login = client.post(
            "/api/v1/admin/session/rehearsal",
            json={"identity": "dev.admin", "rehearsal_secret": REHEARSAL_SECRET},
        )
        assert login.status_code == 200, login.text
        yield client, {"X-EOAT-CSRF-Token": login.json()["csrf_token"]}, login.json()["session_reference"]


def test_phase3_session_is_server_owned_and_csrf_protected(api, seed_records):
    client, csrf, _session_reference = api
    identifier = seed_records[0]
    record = client.get(f"/api/v1/admin/data/eoats/{identifier}")
    assert record.status_code == 200
    denied = client.patch(
        f"/api/v1/admin/data/eoats/{identifier}",
        json={"display_name": "Blocked by CSRF", "expected_row_version": record.json()["row_version"]},
        headers={"Idempotency-Key": f"p3-no-csrf-{RUN}"},
    )
    assert denied.status_code == 403
    assert denied.json()["error_code"] == "CSRF_INVALID"

    changed = client.patch(
        f"/api/v1/admin/data/eoats/{identifier}",
        json={"display_name": "Phase 3 governed", "expected_row_version": record.json()["row_version"]},
        headers={**csrf, "Idempotency-Key": f"p3-update-{RUN}"},
    )
    assert changed.status_code == 200, changed.text
    body = changed.json()
    assert body["record"]["display_name"] == "Phase 3 governed"
    assert body["audit_event_id"]

    stale = client.patch(
        f"/api/v1/admin/data/eoats/{identifier}",
        json={"display_name": "Stale overwrite", "expected_row_version": record.json()["row_version"]},
        headers={**csrf, "Idempotency-Key": f"p3-stale-{RUN}"},
    )
    assert stale.status_code == 409

    with create_session_factory(migration=True)() as session:
        event = session.scalar(select(db.AuditEvent).where(db.AuditEvent.event_id == body["audit_event_id"]))
        assert event is not None
        assert event.source_client == "web"
        assert event.action == "UPDATE"
        assert event.actor_directory_name == "dev.admin"


def test_phase3_bulk_and_settings_are_atomic_and_audited(api, seed_records):
    client, csrf, _session_reference = api
    identifiers, setting_key, secret_setting_key = seed_records
    records = [client.get(f"/api/v1/admin/data/eoats/{identifier}").json() for identifier in identifiers]
    versions = {record["business_identifier"]: record["row_version"] for record in records}
    preview = client.post(
        "/api/v1/admin/data/eoats/bulk-status/preview",
        json={"identifiers": identifiers, "status": "active", "expected_versions": versions},
    )
    assert preview.status_code == 200, preview.text
    committed = client.post(
        "/api/v1/admin/data/eoats/bulk-status/commit",
        json={
            "identifiers": identifiers,
            "status": "active",
            "expected_versions": versions,
            "reason": "Phase 3 isolated bulk acceptance",
            "confirmation": f"BULK STATUS {len(identifiers)}",
        },
        headers={**csrf, "Idempotency-Key": f"p3-bulk-{RUN}"},
    )
    assert committed.status_code == 200, committed.text
    assert committed.json()["atomic"] is True
    assert committed.json()["affected_count"] == 2

    settings = client.get("/api/v1/admin/settings")
    setting = next(value for value in settings.json()["items"] if value["key"] == setting_key)
    changed = client.patch(
        f"/api/v1/admin/settings/{setting_key}",
        json={"value": True, "expected_row_version": setting["row_version"], "reason": "Phase 3 setting acceptance"},
        headers={**csrf, "Idempotency-Key": f"p3-setting-{RUN}"},
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["setting"]["value"] is True

    settings = client.get("/api/v1/admin/settings")
    secret = next(value for value in settings.json()["items"] if value["key"] == secret_setting_key)
    synthetic_secret = "phase3-synthetic-secret-never-disclose"
    secret_changed = client.patch(
        f"/api/v1/admin/settings/{secret_setting_key}",
        json={"value": synthetic_secret, "expected_row_version": secret["row_version"], "reason": "Phase 3 secret acceptance"},
        headers={**csrf, "Idempotency-Key": f"p3-secret-{RUN}"},
    )
    assert secret_changed.status_code == 200, secret_changed.text
    assert synthetic_secret not in secret_changed.text
    with create_session_factory(migration=True)() as session:
        event = session.scalar(select(db.AuditEvent).where(db.AuditEvent.event_id == secret_changed.json()["audit_event_id"]))
        assert event is not None
        assert synthetic_secret not in str(event.before_state_json)
        assert synthetic_secret not in str(event.after_state_json)


def test_phase3_rejects_actor_forgery_and_allows_controlled_session_revocation(api, seed_records):
    client, csrf, session_reference = api
    identifier = seed_records[0][0]
    current = client.get(f"/api/v1/admin/data/eoats/{identifier}")
    forged = client.patch(
        f"/api/v1/admin/data/eoats/{identifier}",
        json={
            "display_name": "Phase 3 forged actor attempt",
            "expected_row_version": current.json()["row_version"],
            "actor_id": 999999,
            "actor_name": "forged",
            "role": "ADMINISTRATOR",
        },
        headers={**csrf, "Idempotency-Key": f"p3-forgery-{RUN}"},
    )
    assert forged.status_code in {200, 422}, forged.text
    if forged.status_code == 200:
        with create_session_factory(migration=True)() as session:
            event = session.scalar(select(db.AuditEvent).where(db.AuditEvent.event_id == forged.json()["audit_event_id"]))
            assert event is not None and event.actor_directory_name == "dev.admin"

    sessions = client.get("/api/v1/admin/access/sessions")
    assert sessions.status_code == 200, sessions.text
    target = next(value for value in sessions.json()["items"] if value["session_reference"] == session_reference)
    revoked = client.post(
        f"/api/v1/admin/access/sessions/{target['session_reference']}/revoke",
        json={"reason": "Phase 3 isolated revocation", "confirmation": f"REVOKE {target['session_reference']}"},
        headers={**csrf, "Idempotency-Key": f"p3-revoke-{RUN}"},
    )
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["audit_event_id"]


def test_phase3_required_audit_failure_rolls_back_business_mutation(api, seed_records, monkeypatch):
    client, csrf, _session_reference = api
    identifier = seed_records[0][1]
    before = client.get(f"/api/v1/admin/data/eoats/{identifier}").json()

    def fail_required_audit(*_args, **_kwargs):
        raise RuntimeError("forced phase3 audit persistence failure")

    monkeypatch.setattr("server.eoat_api.write_services.AuditEventWriter.write_change", fail_required_audit)
    failed = client.patch(
        f"/api/v1/admin/data/eoats/{identifier}",
        json={"display_name": "Must not persist", "expected_row_version": before["row_version"]},
        headers={**csrf, "Idempotency-Key": f"p3-audit-failure-{RUN}"},
    )
    assert failed.status_code >= 500
    after = client.get(f"/api/v1/admin/data/eoats/{identifier}")
    assert after.status_code == 200
    assert after.json()["display_name"] == before["display_name"]
    assert after.json()["row_version"] == before["row_version"]


def test_phase3_capability_denial_leaves_authoritative_data_unchanged(seed_records):
    identifier = seed_records[0][1]
    with TestClient(app, raise_server_exceptions=False) as client:
        login = client.post(
            "/api/v1/admin/session/rehearsal",
            json={"identity": "dev.viewer", "rehearsal_secret": REHEARSAL_SECRET},
        )
        assert login.status_code == 200, login.text
        before = client.get(f"/api/v1/admin/data/eoats/{identifier}")
        assert before.status_code == 403
        denied = client.patch(
            f"/api/v1/admin/data/eoats/{identifier}",
            json={"display_name": "Viewer must not change", "expected_row_version": 1},
            headers={"X-EOAT-CSRF-Token": login.json()["csrf_token"], "Idempotency-Key": f"p3-viewer-denied-{RUN}"},
        )
        assert denied.status_code == 403
    with create_session_factory(migration=True)() as session:
        record = session.scalar(select(db.EOAT).where(db.EOAT.business_identifier == identifier))
        assert record is not None and record.display_name != "Viewer must not change"
