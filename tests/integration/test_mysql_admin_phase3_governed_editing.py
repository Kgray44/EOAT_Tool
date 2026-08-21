from __future__ import annotations

import json
import os
from datetime import datetime, timezone
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
    bulk_status = f"phase3-{RUN}-status"
    with factory() as session, session.begin():
        session.add(
            db.AssetStatus(
                code=bulk_status,
                display_name="Phase 3 acceptance status",
                description="Disposable real-MySQL bulk-status acceptance lookup",
                sort_order=999,
                is_active=True,
            )
        )
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
    return identifiers, setting_key, secret_setting_key, bulk_status


@pytest.fixture(scope="module")
def governed_records():
    """Namespaced real-MySQL records covering each Phase 3 mutation service."""
    factory = create_session_factory(migration=True)
    values = {
        "eoat": f"P3-GOV-{RUN}",
        "machine": f"P3-M-{RUN}",
        "tool": f"P3-T-{RUN}",
        "document_number": f"P3-DOC-{RUN}",
    }
    with factory() as session, session.begin():
        plant = db.Plant(plant_code=f"P3-{RUN}", plant_name="Phase 3 governed-editing plant", source_system="integration_test")
        document_type = db.DocumentType(code=f"p3-{RUN}-document", display_name="Phase 3 acceptance document")
        compatibility = db.CompatibilityStatus(code=f"p3-{RUN}-compatible", display_name="Phase 3 compatible")
        bulk_status = db.AssetStatus(code=f"p3-{RUN}-bulk", display_name="Phase 3 bulk target")
        session.add_all([plant, document_type, compatibility, bulk_status])
        session.flush()
        session.add_all(
            [
                db.EOAT(business_identifier=values["eoat"], display_name="Governed before", source_system="integration_test"),
                db.Machine(
                    plant_id=plant.id,
                    machine_number=values["machine"],
                    machine_name="Governed machine before",
                    source_system="integration_test",
                ),
                db.Tool(
                    business_identifier=values["tool"],
                    tool_number=f"P3-TN-{RUN}",
                    display_name="Governed tool before",
                    source_system="integration_test",
                ),
            ]
        )
        document = db.Document(
            document_uuid=str(uuid4()),
            document_type_id=document_type.id,
            document_number=values["document_number"],
            title="Governed document before",
            file_name="phase3-acceptance.txt",
            storage_path="acceptance://phase3/governed-document",
            source_system="integration_test",
        )
        photo_document = db.Document(
            document_uuid=str(uuid4()),
            document_type_id=document_type.id,
            title="Governed photo before",
            file_name="phase3-acceptance-photo.jpg",
            storage_path="acceptance://phase3/governed-photo",
            source_system="integration_test",
        )
        session.add_all([document, photo_document])
        session.flush()
        photo = db.Photo(document_id=photo_document.id, caption="Photo before", photo_view_type="overview")
        session.add(photo)
        session.flush()
        values.update(
            {
                "compatibility_status": compatibility.code,
                "bulk_status": bulk_status.code,
                "document_id": document.id,
                "photo_id": photo.id,
                "photo_document_id": photo_document.id,
            }
        )
    return values


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
    identifier = seed_records[0][0]
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
    identifiers, setting_key, secret_setting_key, bulk_status = seed_records
    records = [client.get(f"/api/v1/admin/data/eoats/{identifier}").json() for identifier in identifiers]
    versions = {record["business_identifier"]: record["row_version"] for record in records}
    preview = client.post(
        "/api/v1/admin/data/eoats/bulk-status/preview",
        json={"identifiers": identifiers, "status": bulk_status, "expected_versions": versions},
    )
    assert preview.status_code == 200, preview.text
    committed = client.post(
        "/api/v1/admin/data/eoats/bulk-status/commit",
        json={
            "identifiers": identifiers,
            "status": bulk_status,
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
        changes = session.scalars(select(db.AuditChange).where(db.AuditChange.audit_event_id == event.event_id)).all()
        assert event.before_state_json == {"replacement_recorded": False}
        assert event.after_state_json == {"replacement_recorded": True}
        assert synthetic_secret not in json.dumps(
            {"before": event.before_state_json, "after": event.after_state_json, "metadata": event.metadata_json, "changes": [(value.before_value_json, value.after_value_json) for value in changes]}
        )
    secret_listing = client.get("/api/v1/admin/settings")
    assert secret_listing.status_code == 200 and synthetic_secret not in secret_listing.text


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
    denied_after_revoke = client.get("/api/v1/admin/data/eoats")
    assert denied_after_revoke.status_code == 401


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


def test_phase3_required_audit_failure_rolls_back_distinct_mutation_architectures(api, seed_records, governed_records, monkeypatch):
    """Audit is mandatory for service-specific writes, not just asset editing."""
    client, csrf, _session_reference = api
    document = client.get(f"/api/v1/admin/documents/{governed_records['document_id']}").json()
    setting = next(item for item in client.get("/api/v1/admin/settings").json()["items"] if item["key"] == seed_records[1])
    bulk_identifiers = list(seed_records[0])
    bulk_records = {identifier: client.get(f"/api/v1/admin/data/eoats/{identifier}").json() for identifier in bulk_identifiers}
    versions = {identifier: record["row_version"] for identifier, record in bulk_records.items()}
    with create_session_factory(migration=True)() as session:
        audit_before = session.scalar(select(__import__("sqlalchemy").func.count()).select_from(db.AuditEvent))
        active_relationships_before = session.scalar(
            select(__import__("sqlalchemy").func.count()).select_from(db.EOATMachineCompatibility).where(db.EOATMachineCompatibility.is_active.is_(True))
        )

    def fail_required_audit(*_args, **_kwargs):
        raise RuntimeError("forced phase3 audit persistence failure")

    monkeypatch.setattr("server.eoat_api.write_services.AuditEventWriter.write_change", fail_required_audit)
    document_failed = client.patch(
        f"/api/v1/admin/documents/{governed_records['document_id']}",
        json={"title": "must not persist document", "expected_row_version": document["row_version"]},
        headers={**csrf, "Idempotency-Key": f"p3-audit-failure-document-{RUN}"},
    )
    setting_failed = client.patch(
        f"/api/v1/admin/settings/{setting['key']}",
        json={"value": True, "expected_row_version": setting["row_version"], "reason": "must not persist setting"},
        headers={**csrf, "Idempotency-Key": f"p3-audit-failure-setting-{RUN}"},
    )
    relationship_failed = client.post(
        "/api/v1/admin/data/relationships/eoat-machine",
        json={
            "eoat_identifier": governed_records["eoat"],
            "machine_number": governed_records["machine"],
            "compatibility_status": governed_records["compatibility_status"],
            "effective_from": datetime.now(timezone.utc).isoformat(),
            "confirmation": "LINK eoat-machine",
        },
        headers={**csrf, "Idempotency-Key": f"p3-audit-failure-relationship-{RUN}"},
    )
    bulk_failed = client.post(
        "/api/v1/admin/data/eoats/bulk-status/commit",
        json={
            "identifiers": bulk_identifiers,
            "status": governed_records["bulk_status"],
            "expected_versions": versions,
            "reason": "must not persist bulk",
            "confirmation": "BULK STATUS 2",
        },
        headers={**csrf, "Idempotency-Key": f"p3-audit-failure-bulk-{RUN}"},
    )
    assert all(response.status_code >= 500 for response in (document_failed, setting_failed, relationship_failed, bulk_failed))
    with create_session_factory(migration=True)() as session:
        persisted_document = session.get(db.Document, governed_records["document_id"])
        persisted_setting = session.scalar(select(db.SystemSetting).where(db.SystemSetting.setting_key == setting["key"]))
        audit_after = session.scalar(select(__import__("sqlalchemy").func.count()).select_from(db.AuditEvent))
        active_relationships_after = session.scalar(
            select(__import__("sqlalchemy").func.count()).select_from(db.EOATMachineCompatibility).where(db.EOATMachineCompatibility.is_active.is_(True))
        )
        assert persisted_document is not None and persisted_document.title == document["title"]
        assert persisted_setting is not None and persisted_setting.setting_value_json == setting["value"]
        assert audit_after == audit_before
        assert active_relationships_after == active_relationships_before
    for identifier, before in bulk_records.items():
        after = client.get(f"/api/v1/admin/data/eoats/{identifier}").json()
        assert after == before


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


def test_phase3_eoat_edit_correction_lifecycle_and_idempotency_are_real_mysql_audited(api, governed_records):
    client, csrf, _session_reference = api
    identifier = governed_records["eoat"]
    initial = client.get(f"/api/v1/admin/data/eoats/{identifier}")
    assert initial.status_code == 200
    before_version = initial.json()["row_version"]

    update_key = f"p3-governed-eoat-update-{RUN}"
    update_payload = {
        "display_name": "Governed one-field edit",
        "description": "Two material fields are deliberately committed together.",
        "expected_row_version": before_version,
    }
    updated = client.patch(
        f"/api/v1/admin/data/eoats/{identifier}", json=update_payload, headers={**csrf, "Idempotency-Key": update_key}
    )
    assert updated.status_code == 200, updated.text
    replay = client.patch(
        f"/api/v1/admin/data/eoats/{identifier}", json=update_payload, headers={**csrf, "Idempotency-Key": update_key}
    )
    assert replay.status_code == 200
    assert replay.json()["audit_event_id"] == updated.json()["audit_event_id"]
    assert replay.json()["idempotent_replay"] is True
    event_id = updated.json()["audit_event_id"]
    with create_session_factory(migration=True)() as session:
        event = session.scalar(select(db.AuditEvent).where(db.AuditEvent.event_id == event_id))
        assert event is not None
        assert event.action == "UPDATE" and event.actor_directory_name == "dev.admin"
        assert event.before_state_json["display_name"] == "Governed before"
        assert event.after_state_json["display_name"] == "Governed one-field edit"
        assert {"display_name", "description"}.issubset(event.changed_fields_json)
        assert event.request_id and event.correlation_id and event.correlation_id == event.request_id
        assert session.scalars(select(db.AuditChange).where(db.AuditChange.audit_event_id == event_id)).all()

    stale = client.patch(
        f"/api/v1/admin/data/eoats/{identifier}",
        json={"display_name": "stale write", "expected_row_version": before_version},
        headers={**csrf, "Idempotency-Key": f"p3-governed-eoat-stale-{RUN}"},
    )
    assert stale.status_code == 409
    invalid = client.patch(
        f"/api/v1/admin/data/eoats/{identifier}",
        json={"number_of_parts_picked": -1, "expected_row_version": updated.json()["record"]["row_version"]},
        headers={**csrf, "Idempotency-Key": f"p3-governed-eoat-invalid-{RUN}"},
    )
    assert invalid.status_code == 422

    spoofed = client.patch(
        f"/api/v1/admin/data/eoats/{identifier}",
        json={"notes": "Server-derived actor remains authoritative", "expected_row_version": updated.json()["record"]["row_version"]},
        headers={
            **csrf,
            "Idempotency-Key": f"p3-governed-eoat-spoofed-headers-{RUN}",
            "X-EOAT-Identity": "dev.viewer",
            "X-EOAT-Role": "VIEWER",
            "X-EOAT-Administrator": "false",
        },
    )
    assert spoofed.status_code == 200
    with create_session_factory(migration=True)() as session:
        spoofed_event = session.scalar(select(db.AuditEvent).where(db.AuditEvent.event_id == spoofed.json()["audit_event_id"]))
        assert spoofed_event is not None and spoofed_event.actor_directory_name == "dev.admin"

    correction = client.patch(
        f"/api/v1/admin/data/eoats/{identifier}/correction",
        json={
            "display_name": "Governed corrected value",
            "expected_row_version": spoofed.json()["record"]["row_version"],
            "reason": "Correct synthetic acceptance value",
        },
        headers={**csrf, "Idempotency-Key": f"p3-governed-eoat-correction-{RUN}"},
    )
    assert correction.status_code == 200, correction.text
    archived = client.post(
        f"/api/v1/admin/data/eoats/{identifier}/archive",
        json={
            "expected_row_version": correction.json()["record"]["row_version"],
            "reason": "Archive governed acceptance EOAT",
            "confirmation": f"ARCHIVE {identifier}",
        },
        headers={**csrf, "Idempotency-Key": f"p3-governed-eoat-archive-{RUN}"},
    )
    assert archived.status_code == 200 and archived.json()["record"]["is_active"] is False
    restored = client.post(
        f"/api/v1/admin/data/eoats/{identifier}/restore",
        json={
            "expected_row_version": archived.json()["record"]["row_version"],
            "reason": "Restore governed acceptance EOAT",
            "confirmation": f"RESTORE {identifier}",
        },
        headers={**csrf, "Idempotency-Key": f"p3-governed-eoat-restore-{RUN}"},
    )
    assert restored.status_code == 200 and restored.json()["record"]["is_active"] is True
    with create_session_factory(migration=True)() as session:
        original = session.scalar(select(db.AuditEvent).where(db.AuditEvent.event_id == event_id))
        correction_event = session.scalar(select(db.AuditEvent).where(db.AuditEvent.event_id == correction.json()["audit_event_id"]))
        archive_event = session.scalar(select(db.AuditEvent).where(db.AuditEvent.event_id == archived.json()["audit_event_id"]))
        restore_event = session.scalar(select(db.AuditEvent).where(db.AuditEvent.event_id == restored.json()["audit_event_id"]))
        assert original is not None and original.after_state_json["display_name"] == "Governed one-field edit"
        assert correction_event is not None and correction_event.action == "CORRECTION"
        assert correction_event.reason_or_note == "Correct synthetic acceptance value"
        assert archive_event is not None and archive_event.action == "ARCHIVE"
        assert restore_event is not None and restore_event.action == "RESTORE"


def test_phase3_machine_and_tool_mutations_validate_conflicts_and_audit(api, governed_records):
    client, csrf, _session_reference = api
    matrix = (("machines", governed_records["machine"], "machine_name", "Governed machine after", "press_capacity_tons"), ("tools", governed_records["tool"], "display_name", "Governed tool after", "cavity_count"))
    for kind, identifier, field, value, invalid_field in matrix:
        current = client.get(f"/api/v1/admin/data/{kind}/{identifier}")
        assert current.status_code == 200
        version = current.json()["row_version"]
        changed = client.patch(
            f"/api/v1/admin/data/{kind}/{identifier}",
            json={field: value, "expected_row_version": version},
            headers={**csrf, "Idempotency-Key": f"p3-{kind}-update-{RUN}"},
        )
        assert changed.status_code == 200, changed.text
        stale = client.patch(
            f"/api/v1/admin/data/{kind}/{identifier}",
            json={field: "stale", "expected_row_version": version},
            headers={**csrf, "Idempotency-Key": f"p3-{kind}-stale-{RUN}"},
        )
        assert stale.status_code == 409
        invalid = client.patch(
            f"/api/v1/admin/data/{kind}/{identifier}",
            json={invalid_field: -1, "expected_row_version": changed.json()["record"]["row_version"]},
            headers={**csrf, "Idempotency-Key": f"p3-{kind}-invalid-{RUN}"},
        )
        assert invalid.status_code == 422
        with create_session_factory(migration=True)() as session:
            event = session.scalar(select(db.AuditEvent).where(db.AuditEvent.event_id == changed.json()["audit_event_id"]))
            assert event is not None and event.action == "UPDATE" and field in event.changed_fields_json


def test_phase3_relationship_link_rejection_and_unlink_are_audited(api, governed_records):
    client, csrf, _session_reference = api
    relationship_list = client.get("/api/v1/admin/data/relationships/eoat-machine")
    assert relationship_list.status_code == 200, relationship_list.text
    effective_from = datetime.now(timezone.utc).isoformat()
    payload = {
        "eoat_identifier": governed_records["eoat"],
        "machine_number": governed_records["machine"],
        "compatibility_status": governed_records["compatibility_status"],
        "effective_from": effective_from,
        "attributes": {"connection_compatible": True},
        "reason": "Link only server-resolved identifiers",
        "confirmation": "LINK eoat-machine",
    }
    linked = client.post(
        "/api/v1/admin/data/relationships/eoat-machine",
        json=payload,
        headers={**csrf, "Idempotency-Key": f"p3-relationship-link-{RUN}"},
    )
    assert linked.status_code == 200, linked.text
    relationship = linked.json()["record"]
    assert relationship["eoat_id"] and relationship["machine_id"]
    duplicate = client.post(
        "/api/v1/admin/data/relationships/eoat-machine",
        json=payload,
        headers={**csrf, "Idempotency-Key": f"p3-relationship-duplicate-{RUN}"},
    )
    assert duplicate.status_code == 409 and duplicate.json()["error_code"] == "DUPLICATE_ACTIVE_RELATIONSHIP"
    invalid_selector = client.post(
        "/api/v1/admin/data/relationships/eoat-tool",
        json={
            "eoat_identifier": governed_records["eoat"],
            "tool_identifier": "not-a-server-resolved-tool",
            "compatibility_status": governed_records["compatibility_status"],
            "effective_from": effective_from,
            "confirmation": "LINK eoat-tool",
        },
        headers={**csrf, "Idempotency-Key": f"p3-relationship-selector-{RUN}"},
    )
    assert invalid_selector.status_code == 404
    invalid_compatibility = client.post(
        "/api/v1/admin/data/relationships/eoat-tool",
        json={
            "eoat_identifier": governed_records["eoat"],
            "tool_identifier": governed_records["tool"],
            "compatibility_status": "free-text-compatibility-bypass",
            "effective_from": effective_from,
            "confirmation": "LINK eoat-tool",
        },
        headers={**csrf, "Idempotency-Key": f"p3-relationship-compatibility-{RUN}"},
    )
    assert invalid_compatibility.status_code == 422
    preview = client.get(
        f"/api/v1/admin/data/relationships/eoat-machine/{relationship['id']}/unlink-preview"
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["confirmation_phrase"].startswith("Unlink EOAT ")
    unlinked = client.post(
        f"/api/v1/admin/data/relationships/eoat-machine/{relationship['id']}/unlink",
        json={
            "expected_row_version": preview.json()["row_version"],
            "reason": "Unlink governed acceptance relationship",
            "confirmation": preview.json()["confirmation_phrase"],
        },
        headers={**csrf, "Idempotency-Key": f"p3-relationship-unlink-{RUN}"},
    )
    assert unlinked.status_code == 200 and unlinked.json()["record"]["is_active"] is False
    with create_session_factory(migration=True)() as session:
        link_event = session.scalar(select(db.AuditEvent).where(db.AuditEvent.event_id == linked.json()["audit_event_id"]))
        unlink_event = session.scalar(select(db.AuditEvent).where(db.AuditEvent.event_id == unlinked.json()["audit_event_id"]))
        assert link_event is not None and link_event.action == "LINK"
        assert unlink_event is not None and unlink_event.action == "UNLINK"


def test_phase3_document_and_photo_metadata_archive_are_safe_and_audited(api, governed_records):
    client, csrf, _session_reference = api
    document = client.get(f"/api/v1/admin/documents/{governed_records['document_id']}")
    assert document.status_code == 200 and "storage_path" not in document.text
    changed = client.patch(
        f"/api/v1/admin/documents/{governed_records['document_id']}",
        json={"title": "Governed document after", "revision": "P3-R2", "expected_row_version": document.json()["row_version"]},
        headers={**csrf, "Idempotency-Key": f"p3-document-update-{RUN}"},
    )
    assert changed.status_code == 200 and "storage_path" not in changed.text
    archived = client.post(
        f"/api/v1/admin/documents/{governed_records['document_id']}/archive",
        json={
            "expected_row_version": changed.json()["record"]["row_version"],
            "reason": "Archive governed document",
            "confirmation": f"ARCHIVE DOCUMENT {governed_records['document_id']}",
        },
        headers={**csrf, "Idempotency-Key": f"p3-document-archive-{RUN}"},
    )
    assert archived.status_code == 200 and archived.json()["record"]["is_active"] is False
    photos = client.get("/api/v1/admin/photos")
    photo = next(item for item in photos.json()["items"] if item["photo"]["id"] == governed_records["photo_id"])
    photo_changed = client.patch(
        f"/api/v1/admin/photos/{governed_records['photo_id']}",
        json={"caption": "Governed photo after", "expected_row_version": photo["row_version"]},
        headers={**csrf, "Idempotency-Key": f"p3-photo-update-{RUN}"},
    )
    assert photo_changed.status_code == 200 and "storage_path" not in photo_changed.text
    photo_archived = client.post(
        f"/api/v1/admin/photos/{governed_records['photo_id']}/archive",
        json={
            "expected_row_version": photo_changed.json()["record"]["document"]["row_version"],
            "reason": "Archive governed photo",
            "confirmation": f"ARCHIVE PHOTO {governed_records['photo_id']}",
        },
        headers={**csrf, "Idempotency-Key": f"p3-photo-archive-{RUN}"},
    )
    assert photo_archived.status_code == 200 and photo_archived.json()["record"]["document"]["is_active"] is False
    with create_session_factory(migration=True)() as session:
        document_event = session.scalar(select(db.AuditEvent).where(db.AuditEvent.event_id == changed.json()["audit_event_id"]))
        document_archive = session.scalar(select(db.AuditEvent).where(db.AuditEvent.event_id == archived.json()["audit_event_id"]))
        photo_event = session.scalar(select(db.AuditEvent).where(db.AuditEvent.event_id == photo_changed.json()["audit_event_id"]))
        photo_archive = session.scalar(select(db.AuditEvent).where(db.AuditEvent.event_id == photo_archived.json()["audit_event_id"]))
        assert document_event is not None and document_event.action == "METADATA_CHANGE"
        assert document_archive is not None and document_archive.action == "ARCHIVE"
        assert photo_event is not None and photo_event.action == "METADATA_CHANGE"
        assert photo_archive is not None and photo_archive.action == "PHOTO_ARCHIVE"


def test_phase3_bulk_preview_rejection_commit_and_correlated_ledger_evidence(api, seed_records, governed_records):
    client, csrf, _session_reference = api
    target_one, target_two = governed_records["eoat"], seed_records[0][1]
    records = {identifier: client.get(f"/api/v1/admin/data/eoats/{identifier}").json() for identifier in (target_one, target_two)}
    versions = {identifier: records[identifier]["row_version"] for identifier in records}
    preview = client.post(
        "/api/v1/admin/data/eoats/bulk-status/preview",
        json={"identifiers": [target_one, target_two], "status": governed_records["bulk_status"], "expected_versions": versions},
    )
    assert preview.status_code == 200 and preview.json()["count"] == 2 and preview.json()["atomic"] is True
    assert {row["identifier"] for row in preview.json()["records"]} == {target_one, target_two}
    zero_target = client.post(
        "/api/v1/admin/data/eoats/bulk-status/preview",
        json={"identifiers": [], "status": governed_records["bulk_status"], "expected_versions": {}},
    )
    assert zero_target.status_code == 422
    invalid_target = client.post(
        "/api/v1/admin/data/eoats/bulk-status/commit",
        json={
            "identifiers": [target_one, "not-a-real-bulk-target"],
            "status": governed_records["bulk_status"],
            "expected_versions": {target_one: versions[target_one], "not-a-real-bulk-target": 1},
            "reason": "Invalid bulk target must be atomic",
            "confirmation": "BULK STATUS 2",
        },
        headers={**csrf, "Idempotency-Key": f"p3-bulk-invalid-{RUN}"},
    )
    assert invalid_target.status_code == 404
    unchanged = client.get(f"/api/v1/admin/data/eoats/{target_one}").json()
    assert unchanged["row_version"] == versions[target_one]
    key = f"p3-bulk-commit-{RUN}"
    committed = client.post(
        "/api/v1/admin/data/eoats/bulk-status/commit",
        json={
            "identifiers": [target_one, target_two],
            "status": governed_records["bulk_status"],
            "expected_versions": versions,
            "reason": "Bulk status acceptance commit",
            "confirmation": "BULK STATUS 2",
        },
        headers={**csrf, "Idempotency-Key": key},
    )
    assert committed.status_code == 200, committed.text
    assert committed.json()["affected_count"] == 2 and committed.json()["failed_count"] == 0 and committed.json()["atomic"] is True
    replay = client.post(
        "/api/v1/admin/data/eoats/bulk-status/commit",
        json={
            "identifiers": [target_one, target_two],
            "status": governed_records["bulk_status"],
            "expected_versions": versions,
            "reason": "Bulk status acceptance commit",
            "confirmation": "BULK STATUS 2",
        },
        headers={**csrf, "Idempotency-Key": key},
    )
    assert replay.status_code == 200 and replay.json()["idempotent_replay"] is True
    correlation_id = committed.json()["correlation_id"]
    with create_session_factory(migration=True)() as session:
        events = session.scalars(select(db.AuditEvent).where(db.AuditEvent.correlation_id == correlation_id)).all()
        actions = [event.action for event in events]
        assert actions.count("STATUS_CHANGE") == 2 and actions.count("BULK_OPERATION") == 1
        parent = next(event for event in events if event.action == "BULK_OPERATION")
        assert parent.after_state_json == {"count": 2, "status": governed_records["bulk_status"]}


def test_phase3_settings_and_development_role_mapping_are_governed(api, seed_records):
    client, csrf, _session_reference = api
    setting_key = seed_records[1]
    setting = next(value for value in client.get("/api/v1/admin/settings").json()["items"] if value["key"] == setting_key)
    changed = client.patch(
        f"/api/v1/admin/settings/{setting_key}",
        json={"value": False, "expected_row_version": setting["row_version"], "reason": "Safe non-secret setting acceptance"},
        headers={**csrf, "Idempotency-Key": f"p3-setting-safe-{RUN}"},
    )
    assert changed.status_code == 200 and changed.json()["setting"]["value"] is False
    mappings = client.get("/api/v1/admin/access/test-mappings")
    assert mappings.status_code == 200
    viewer = next(value for value in mappings.json()["items"] if value["identity"] == "dev.viewer" and value["environment"] == "development")
    mapping_changed = client.patch(
        "/api/v1/admin/access/test-mappings/dev.viewer",
        json={"role_code": "ADMIN_AUDITOR", "expected_row_version": viewer["row_version"], "reason": "Development-only role rehearsal"},
        headers={**csrf, "Idempotency-Key": f"p3-mapping-valid-{RUN}"},
    )
    assert mapping_changed.status_code == 200 and mapping_changed.json()["mapping"]["role_code"] == "ADMIN_AUDITOR"
    invalid_role = client.patch(
        "/api/v1/admin/access/test-mappings/dev.viewer",
        json={"role_code": "PRODUCTION_DIRECTORY_ADMIN", "expected_row_version": mapping_changed.json()["mapping"]["row_version"], "reason": "Must reject invalid role"},
        headers={**csrf, "Idempotency-Key": f"p3-mapping-invalid-{RUN}"},
    )
    assert invalid_role.status_code == 422
    with TestClient(app, raise_server_exceptions=False) as viewer_client:
        login = viewer_client.post("/api/v1/admin/session/rehearsal", json={"identity": "dev.viewer", "rehearsal_secret": REHEARSAL_SECRET})
        assert login.status_code == 200
        denied = viewer_client.patch(
            f"/api/v1/admin/settings/{setting_key}",
            json={"value": True, "expected_row_version": changed.json()["setting"]["row_version"], "reason": "Auditor must not edit settings"},
            headers={"X-EOAT-CSRF-Token": login.json()["csrf_token"], "Idempotency-Key": f"p3-mapping-denied-{RUN}"},
        )
        assert denied.status_code == 403
    restored = client.patch(
        "/api/v1/admin/access/test-mappings/dev.viewer",
        json={"role_code": "VIEWER", "expected_row_version": mapping_changed.json()["mapping"]["row_version"], "reason": "Restore development fixture"},
        headers={**csrf, "Idempotency-Key": f"p3-mapping-restore-{RUN}"},
    )
    assert restored.status_code == 200 and restored.json()["mapping"]["role_code"] == "VIEWER"
    with create_session_factory(migration=True)() as session:
        setting_event = session.scalar(select(db.AuditEvent).where(db.AuditEvent.event_id == changed.json()["audit_event_id"]))
        mapping_event = session.scalar(select(db.AuditEvent).where(db.AuditEvent.event_id == mapping_changed.json()["audit_event_id"]))
        restoration_event = session.scalar(select(db.AuditEvent).where(db.AuditEvent.event_id == restored.json()["audit_event_id"]))
        assert setting_event is not None and setting_event.action == "SETTINGS_CHANGE"
        assert setting_event.before_state_json == {"value": True} and setting_event.after_state_json == {"value": False}
        assert mapping_event is not None and mapping_event.action == "ROLE_MAPPING_CHANGE"
        assert restoration_event is not None and restoration_event.action == "ROLE_MAPPING_CHANGE"
        assert restoration_event.before_state_json == {"role_code": "ADMIN_AUDITOR"}
        assert restoration_event.after_state_json == {"role_code": "VIEWER"}
