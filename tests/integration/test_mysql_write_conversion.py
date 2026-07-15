from __future__ import annotations

import os
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select
from sqlalchemy.exc import OperationalError

from core.data_gateway.cache_repository import CacheRepository
from core.data_gateway.configuration import GatewayConfiguration
from core.data_gateway.exceptions import (
    ApiUnavailableError,
    ConcurrencyConflictError,
    PermissionDeniedError,
    WriteBlockedError,
)
from core.data_gateway.gateway import AtlasDataGateway
from core.versioning import get_release_info
from server.eoat_api.app import app
from server.eoat_api.database import models as db
from server.eoat_api.database.session import create_session_factory, get_write_session
from server.eoat_api.services import AtlasService

pytestmark = pytest.mark.skipif(
    os.getenv("EOAT_DB_NAME") != "eoat_atlas_test",
    reason="Write conversion integration tests require EOAT_DB_NAME=eoat_atlas_test",
)

ENGINEER = {"X-EOAT-Identity": "dev.engineer"}
TECHNICIAN = {"X-EOAT-Identity": "dev.technician"}
ADMIN = {"X-EOAT-Identity": "dev.admin"}
VIEWER = {"X-EOAT-Identity": "dev.viewer"}


@pytest.fixture(scope="module")
def api():
    with TestClient(app) as client:
        yield client


@pytest.fixture(scope="module", autouse=True)
def base_records():
    factory = create_session_factory(migration=True)
    with factory() as session, session.begin():
        plant = db.Plant(plant_code="TEST", plant_name="Write Test Plant", source_system="integration_test")
        session.add(plant)
        session.flush()
        location = db.StorageLocation(
            plant_id=plant.id,
            location_code="TEST-STORAGE",
            location_name="Integration Test Storage",
            source_system="integration_test",
        )
        session.add(location)


def post(api, path, payload, identity=ENGINEER, key=None):
    headers = dict(identity)
    if key:
        headers["Idempotency-Key"] = key
    return api.post(path, json=payload, headers=headers)


def test_authorization_boundary_and_unknown_identity(api):
    payload = {"business_identifier": "AUTH-BLOCKED"}
    assert post(api, "/api/v1/eoats", payload, VIEWER, "viewer-block").status_code == 403
    assert post(api, "/api/v1/eoats", payload, {"X-EOAT-Identity": "unknown"}, "unknown-block").status_code == 401
    with create_session_factory(migration=True)() as session:
        assert session.scalar(select(func.count(db.EOAT.id)).where(db.EOAT.business_identifier == "AUTH-BLOCKED")) == 0
    technician = post(api, "/api/v1/tools", {"business_identifier": "TECH-BLOCKED"}, TECHNICIAN, "tech-block")
    assert technician.status_code == 403


def test_history_endpoint_honestly_returns_empty_for_eoat_without_events(api):
    with create_session_factory(migration=True)() as session, session.begin():
        record = db.EOAT(
            business_identifier="NO-HISTORY-EOAT",
            display_name="No History Scenario",
            source_system="integration_test",
        )
        session.add(record)
    response = api.get("/api/v1/eoats/NO-HISTORY-EOAT/history")
    assert response.status_code == 200
    assert response.json()["items"] == []
    assert response.json()["pagination"]["total"] == 0


def test_asset_writes_idempotency_and_optimistic_concurrency(api):
    create = post(
        api, "/api/v1/eoats", {"business_identifier": "WRITE-EOAT", "display_name": "Original"}, key="eoat-create-1"
    )
    assert create.status_code == 200
    first = create.json()
    replay = post(
        api, "/api/v1/eoats", {"business_identifier": "WRITE-EOAT", "display_name": "Original"}, key="eoat-create-1"
    )
    assert replay.status_code == 200 and replay.json()["id"] == first["id"] and replay.json()["idempotent_replay"]
    changed_body = post(api, "/api/v1/eoats", {"business_identifier": "WRITE-EOAT-DIFFERENT"}, key="eoat-create-1")
    assert changed_body.status_code == 409 and changed_body.json()["error_code"] == "IDEMPOTENCY_KEY_REUSED"
    update = api.patch(
        "/api/v1/eoats/WRITE-EOAT",
        headers=ENGINEER,
        json={"display_name": "Authoritative", "expected_row_version": first["row_version"]},
    )
    assert update.status_code == 200 and update.json()["row_version"] == first["row_version"] + 1
    stale = api.patch(
        "/api/v1/eoats/WRITE-EOAT",
        headers=ENGINEER,
        json={"display_name": "Stale overwrite", "expected_row_version": first["row_version"]},
    )
    assert stale.status_code == 409
    assert stale.json()["current_record_version"] == update.json()["row_version"]
    assert api.get("/api/v1/eoats/WRITE-EOAT").json()["display_name"] == "Authoritative"
    archived = post(
        api,
        "/api/v1/eoats/WRITE-EOAT/archive",
        {"expected_row_version": update.json()["row_version"], "reason": "Archive test"},
        ADMIN,
    )
    assert archived.status_code == 200 and archived.json()["is_active"] is False
    restored = post(
        api,
        "/api/v1/eoats/WRITE-EOAT/restore",
        {"expected_row_version": archived.json()["row_version"], "reason": "Restore test"},
        ADMIN,
    )
    assert restored.status_code == 200 and restored.json()["is_active"] is True


def test_machine_tool_robot_and_compatibility_writes(api):
    machine = post(
        api,
        "/api/v1/machines",
        {"plant_code": "TEST", "machine_number": "WRITE-M1", "machine_name": "Machine"},
        key="machine-create-1",
    )
    tool = post(api, "/api/v1/tools", {"business_identifier": "WRITE-T1", "display_name": "Tool"}, key="tool-create-1")
    robot = post(
        api,
        "/api/v1/robots",
        {"plant_code": "TEST", "robot_identifier": "WRITE-R1", "robot_name": "Robot"},
        key="robot-create-1",
    )
    assert {machine.status_code, tool.status_code, robot.status_code} == {200}
    relation = post(
        api,
        "/api/v1/compatibility/eoat-machine",
        {
            "eoat_identifier": "WRITE-EOAT",
            "machine_number": "WRITE-M1",
            "compatibility_status": "compatible",
            "verification_source": "user_verified",
            "effective_from": datetime.now(timezone.utc).isoformat(),
            "reason": "Integration verified",
        },
    )
    assert relation.status_code == 200
    for relationship_type, identifiers in (
        ("eoat-tool", {"eoat_identifier": "WRITE-EOAT", "tool_identifier": "WRITE-T1"}),
        ("tool-machine", {"tool_identifier": "WRITE-T1", "machine_number": "WRITE-M1"}),
    ):
        related = post(
            api,
            f"/api/v1/compatibility/{relationship_type}",
            {
                **identifiers,
                "compatibility_status": "compatible",
                "verification_source": "user_verified",
                "effective_from": datetime.now(timezone.utc).isoformat(),
                "reason": "Integration verified",
            },
        )
        assert related.status_code == 200
    duplicate = post(
        api,
        "/api/v1/compatibility/eoat-machine",
        {
            "eoat_identifier": "WRITE-EOAT",
            "machine_number": "WRITE-M1",
            "compatibility_status": "compatible",
            "effective_from": datetime.now(timezone.utc).isoformat(),
        },
    )
    assert duplicate.status_code == 409


def test_transactional_location_moves_and_stale_race(api):
    eoat = api.get("/api/v1/eoats/WRITE-EOAT").json()
    missing_tool = post(
        api,
        "/api/v1/eoats/WRITE-EOAT/move-to-machine",
        {"machine_number": "WRITE-M1", "expected_row_version": eoat["row_version"], "reason": "Unsafe omission"},
        TECHNICIAN,
        "move-machine-missing-tool",
    )
    assert missing_tool.status_code == 422
    move = post(
        api,
        "/api/v1/eoats/WRITE-EOAT/move-to-machine",
        {
            "plant_code": "TEST",
            "machine_number": "WRITE-M1",
            "tool_identifier": "WRITE-T1",
            "expected_row_version": eoat["row_version"],
            "reason": "Install test",
        },
        TECHNICIAN,
        "move-machine-1",
    )
    assert move.status_code == 200, move.text
    stale_race = post(
        api,
        "/api/v1/eoats/WRITE-EOAT/move-to-storage",
        {"storage_location_code": "TEST-STORAGE", "expected_row_version": eoat["row_version"], "reason": "Stale move"},
        TECHNICIAN,
        "stale-storage-1",
    )
    assert stale_race.status_code == 409
    current = api.get("/api/v1/eoats/WRITE-EOAT").json()
    storage = post(
        api,
        "/api/v1/eoats/WRITE-EOAT/move-to-storage",
        {
            "storage_location_code": "TEST-STORAGE",
            "expected_row_version": current["row_version"],
            "reason": "Store test",
        },
        TECHNICIAN,
        "move-storage-1",
    )
    assert storage.status_code == 200
    with create_session_factory(migration=True)() as session:
        eoat_id = session.scalar(select(db.EOAT.id).where(db.EOAT.business_identifier == "WRITE-EOAT"))
        assert (
            session.scalar(
                select(func.count(db.EOATInstallation.id)).where(
                    db.EOATInstallation.eoat_id == eoat_id, db.EOATInstallation.removed_at.is_(None)
                )
            )
            == 0
        )
        assert (
            session.scalar(
                select(func.count(db.EOATStorageAssignment.id)).where(
                    db.EOATStorageAssignment.eoat_id == eoat_id,
                    db.EOATStorageAssignment.removed_from_storage_at.is_(None),
                )
            )
            == 1
        )


def test_audit_maintenance_fit_check_and_instance_writes(api):
    audit = post(
        api,
        "/api/v1/audits",
        {"audit_identifier": "WRITE-AUDIT", "eoat_identifier": "WRITE-EOAT", "details": {"answer": "yes"}},
        TECHNICIAN,
        "audit-create-1",
    )
    assert audit.status_code == 200
    completed = post(
        api,
        f"/api/v1/audits/{audit.json()['id']}/complete",
        {"expected_row_version": audit.json()["row_version"]},
        TECHNICIAN,
        "audit-complete-1",
    )
    assert completed.status_code == 200
    maintenance = post(
        api,
        "/api/v1/maintenance-events",
        {
            "eoat_identifier": "WRITE-EOAT",
            "event_type": "PM",
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "downtime_minutes": 0,
            "summary": "Integration PM",
        },
        TECHNICIAN,
        "maintenance-create-1",
    )
    assert maintenance.status_code == 200
    done = post(
        api,
        f"/api/v1/maintenance-events/{maintenance.json()['id']}/complete",
        {"expected_row_version": maintenance.json()["row_version"]},
        TECHNICIAN,
        "maintenance-complete-1",
    )
    assert done.status_code == 200
    fit = post(
        api,
        "/api/v1/fit-checks/evaluate",
        {"machine_number": "WRITE-M1", "tool_number": "WRITE-T1", "eoat_identifier": "WRITE-EOAT", "persist": True},
        TECHNICIAN,
    )
    assert fit.status_code == 200 and fit.json()["stored"] is True
    instance_uuid = str(uuid4())
    release = get_release_info()
    registered = post(
        api,
        "/api/v1/application-instances/register",
        {"instance_uuid": instance_uuid, "computer_name": "TEST-PC", **release.provenance()},
        TECHNICIAN,
    )
    assert registered.status_code == 200
    heartbeat = post(api, "/api/v1/application-instances/heartbeat", {"instance_uuid": instance_uuid}, TECHNICIAN)
    assert heartbeat.status_code == 200
    with create_session_factory(migration=True)() as session:
        instance = session.scalar(
            select(db.ApplicationInstance).where(db.ApplicationInstance.instance_uuid == instance_uuid)
        )
        registered_release = session.get(db.ApplicationRelease, instance.application_release_id)
        assert registered_release.application_version == release.application_version
        assert registered_release.release_id == release.release_id
        assert registered_release.build_id == release.build_id
        assert session.scalar(
            select(func.count(db.ChangeAuditLog.id)).where(db.ChangeAuditLog.application_release_id.is_not(None))
        ) > 0


def test_document_tag_and_annotation_writes(api, tmp_path):
    with create_session_factory(migration=True)() as session:
        write_eoat_id = session.scalar(select(db.EOAT.id).where(db.EOAT.business_identifier == "WRITE-EOAT"))
    assert write_eoat_id is not None
    source = tmp_path / "controlled.txt"
    source.write_text("controlled test document", encoding="utf-8")
    document = post(
        api,
        "/api/v1/documents",
        {
            "document_type": "document",
            "title": "Controlled",
            "storage_path": str(source),
            "entity_type": "eoat",
            "entity_id": write_eoat_id,
        },
        ADMIN,
        "document-create-1",
    )
    assert document.status_code == 200
    photo_source = tmp_path / "photo.jpg"
    photo_source.write_bytes(b"not-real-image-but-metadata-safe")
    photo = post(
        api,
        "/api/v1/photos",
        {
            "title": "Metadata photo",
            "storage_path": str(photo_source),
            "caption": "Test",
            "entity_type": "eoat",
            "entity_id": write_eoat_id,
        },
        ADMIN,
        "photo-create-1",
    )
    assert photo.status_code == 200 and photo.json()["photo"]["caption"] == "Test"
    selected = post(
        api,
        f"/api/v1/photos/{photo.json()['photo']['id']}/set-profile",
        {"expected_row_version": photo.json()["row_version"], "reason": "Profile selection test"},
        ENGINEER,
    )
    assert selected.status_code == 200 and selected.json()["photo"]["is_profile_photo"] is True
    missing = post(
        api,
        "/api/v1/documents",
        {"document_type": "document", "title": "Missing", "storage_path": str(tmp_path / "missing.pdf")},
        ENGINEER,
        "document-missing-1",
    )
    assert missing.status_code == 422
    target_uuid = "target_write_integration"
    target = post(
        api,
        "/api/v1/annotation-targets",
        {
            "target_uuid": target_uuid,
            "target_type": "audit_field",
            "target_label": "Write field",
            "audit_identifier": "WRITE-AUDIT",
            "field_key": "sensor",
        },
        TECHNICIAN,
    )
    assert target.status_code == 200
    tag = post(
        api,
        "/api/v1/tags",
        {"tag_code": "write_review", "display_name": "Write Review", "color_key": "yellow"},
        ENGINEER,
    )
    assert tag.status_code == 200
    assignment = post(
        api,
        f"/api/v1/entities/annotation_target/{target_uuid}/tags/{tag.json()['id']}",
        {"comment": "Review"},
        TECHNICIAN,
    )
    assert assignment.status_code == 200
    annotation = post(
        api,
        f"/api/v1/entities/annotation_target/{target_uuid}/annotations",
        {"subject": "Server note", "body": "Exact body", "importance": "Important"},
        TECHNICIAN,
    )
    assert annotation.status_code == 200
    changed = api.patch(
        f"/api/v1/annotations/{annotation.json()['id']}",
        headers=TECHNICIAN,
        json={"body": "Updated body", "expected_row_version": annotation.json()["row_version"]},
    )
    assert changed.status_code == 200 and changed.json()["row_version"] == 2
    second_target_uuid = "target_write_integration_secondary"
    second_target = post(
        api,
        "/api/v1/annotation-targets",
        {
            "target_uuid": second_target_uuid,
            "target_type": "audit_field",
            "target_label": "Secondary write field",
            "audit_identifier": "WRITE-AUDIT",
            "field_key": "gripper",
        },
        TECHNICIAN,
    )
    assert second_target.status_code == 200
    linked = post(
        api,
        f"/api/v1/annotations/{annotation.json()['id']}/targets/{second_target_uuid}",
        {"expected_row_version": changed.json()["row_version"]},
        TECHNICIAN,
    )
    assert linked.status_code == 200 and linked.json()["row_version"] == 3
    linked_notes = api.get(f"/api/v1/entities/annotation_target/{second_target_uuid}/annotations")
    assert [item["id"] for item in linked_notes.json()] == [annotation.json()["id"]]
    note_tag = post(
        api,
        f"/api/v1/entities/annotation/{annotation.json()['id']}/tags/{tag.json()['id']}",
        {},
        TECHNICIAN,
    )
    assert note_tag.status_code == 200
    archived = post(
        api,
        "/api/v1/tag-assignments/archive",
        {"assignment_ids": [assignment.json()["id"], note_tag.json()["id"]]},
        TECHNICIAN,
    )
    assert archived.status_code == 200 and archived.json()["archived_count"] == 2
    unlinked = api.request(
        "DELETE",
        f"/api/v1/annotations/{annotation.json()['id']}/targets/{second_target_uuid}",
        headers=TECHNICIAN,
        json={"expected_row_version": linked.json()["row_version"]},
    )
    assert unlinked.status_code == 200 and unlinked.json()["row_version"] == 4


def test_eoat_history_event_coverage_idempotency_and_archive_restore(api):
    with create_session_factory(migration=True)() as session:
        eoat_id = session.scalar(select(db.EOAT.id).where(db.EOAT.business_identifier == "WRITE-EOAT"))
        tag = session.scalar(select(db.Tag).where(db.Tag.tag_code == "write_review"))
    assignment = post(
        api,
        f"/api/v1/entities/eoat/{eoat_id}/tags/{tag.id}",
        {"comment": "EOAT history coverage"},
        TECHNICIAN,
        "eoat-tag-history-1",
    )
    assert assignment.status_code == 200
    removed = api.request(
        "DELETE",
        f"/api/v1/entities/eoat/{eoat_id}/tags/{tag.id}",
        headers=TECHNICIAN,
        json={"expected_row_version": assignment.json()["row_version"]},
    )
    assert removed.status_code == 200
    annotation = post(
        api,
        f"/api/v1/entities/eoat/{eoat_id}/annotations",
        {"subject": "EOAT note", "body": "Structured EOAT history"},
        TECHNICIAN,
        "eoat-annotation-history-1",
    )
    assert annotation.status_code == 200
    unknown = post(
        api,
        "/api/v1/eoats/WRITE-EOAT/mark-location-unknown",
        {
            "expected_row_version": api.get("/api/v1/eoats/WRITE-EOAT").json()["row_version"],
            "reason": "Archive test",
            "confirm": True,
        },
        TECHNICIAN,
        "eoat-unknown-history-1",
    )
    assert unknown.status_code == 200
    archived = post(
        api,
        "/api/v1/eoats/WRITE-EOAT/archive",
        {"expected_row_version": unknown.json()["row_version"], "reason": "Archive coverage"},
        ADMIN,
        "eoat-archive-history-1",
    )
    assert archived.status_code == 200
    restored = post(
        api,
        "/api/v1/eoats/WRITE-EOAT/restore",
        {"expected_row_version": archived.json()["row_version"], "reason": "Restore coverage"},
        ADMIN,
        "eoat-restore-history-1",
    )
    assert restored.status_code == 200

    history = api.get("/api/v1/eoats/WRITE-EOAT/history", params={"page_size": 200}).json()["items"]
    types = {item["event_type"] for item in history}
    assert {
        "EOAT_CREATED",
        "EOAT_UPDATED",
        "EOAT_ARCHIVED",
        "EOAT_RESTORED",
        "EOAT_INSTALLED_ON_MACHINE",
        "EOAT_MOVED_TO_STORAGE",
        "EOAT_LOCATION_MARKED_UNKNOWN",
        "COMPATIBILITY_CREATED",
        "AUDIT_STARTED",
        "AUDIT_COMPLETED",
        "MAINTENANCE_STARTED",
        "MAINTENANCE_COMPLETED",
        "DOCUMENT_ADDED",
        "PHOTO_ADDED",
        "PROFILE_PHOTO_SELECTED",
        "TAG_ASSIGNED",
        "TAG_REMOVED",
        "ANNOTATION_ADDED",
    }.issubset(types)
    assert all(item["source_record_type"] for item in history if item["event_type"] not in {"EOAT_CREATED", "EOAT_UPDATED", "EOAT_ARCHIVED", "EOAT_RESTORED"})
    with create_session_factory(migration=True)() as session:
        created_type = session.scalar(select(db.HistoryEventType.id).where(db.HistoryEventType.code == "record_created"))
        assert session.scalar(
            select(func.count(db.EntityHistoryEvent.id)).where(
                db.EntityHistoryEvent.entity_type == "eoat",
                db.EntityHistoryEvent.entity_id == eoat_id,
                db.EntityHistoryEvent.event_type_id == created_type,
            )
        ) == 1


def test_failed_business_write_rolls_back_audit_and_change_feed(api):
    factory = create_session_factory(migration=True)
    with factory() as session:
        before_relations = session.scalar(select(func.count(db.EOATToolCompatibility.id)))
        before_audits = session.scalar(select(func.count(db.ChangeAuditLog.id)))
        before_changes = session.scalar(select(func.count(db.ChangeFeed.change_id)))
        before_history = session.scalar(select(func.count(db.EntityHistoryEvent.id)))
        relation = session.scalar(select(db.EOATToolCompatibility).where(db.EOATToolCompatibility.is_active.is_(True)))
    response = api.patch(
        f"/api/v1/compatibility/eoat-tool/{relation.id}",
        headers=ENGINEER,
        json={
            "compatibility_status": "not-a-status",
            "effective_from": datetime.now(timezone.utc).isoformat(),
            "expected_row_version": relation.row_version,
        },
    )
    assert response.status_code == 422
    with factory() as session:
        assert session.scalar(select(func.count(db.EOATToolCompatibility.id))) == before_relations
        assert session.scalar(select(func.count(db.ChangeAuditLog.id))) == before_audits
        assert session.scalar(select(func.count(db.ChangeFeed.change_id))) == before_changes
        assert session.scalar(select(func.count(db.EntityHistoryEvent.id))) == before_history


class ApiTestAdapter:
    def __init__(self, client: TestClient, identity: str = "dev.engineer"):
        self.client = client
        self.identity = identity

    def _get(self, path, **params):
        response = self.client.get(path, params=params)
        response.raise_for_status()
        return response.json()

    def health(self):
        return self._get("/api/v1/health")

    def changes(self, cursor):
        return self._get("/api/v1/sync/changes", after_cursor=cursor)

    def snapshot(self):
        return self._get("/api/v1/sync/snapshot")

    def write(self, method, path, payload=None, *, idempotency_key=None, params=None):
        headers = {"X-EOAT-Identity": self.identity}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        response = self.client.request(method, path, json=payload, headers=headers, params=params)
        if response.status_code == 409 and response.json().get("error_code") == "STALE_RECORD_VERSION":
            raise ConcurrencyConflictError(
                response.json()["message"], current_record_version=response.json().get("current_record_version")
            )
        if response.status_code in {401, 403}:
            raise PermissionDeniedError(response.json()["message"])
        response.raise_for_status()
        return response.json()


class OfflineAdapter:
    def health(self):
        raise ApiUnavailableError("offline")

    def write(self, *args, **kwargs):
        raise AssertionError("offline writes must not be sent")


class FailingRefreshCache(CacheRepository):
    def build_snapshot(self, snapshot, destination):
        raise OSError("simulated cache failure")


def test_two_independent_gateway_caches_and_conflict(api, tmp_path):
    config_a = GatewayConfiguration(
        backend="mysql_api",
        cache_path=tmp_path / "client-a.db",
        expected_schema_revision="20260715_0006",
        writes_enabled=True,
        environment="development",
    )
    config_b = GatewayConfiguration(
        backend="mysql_api",
        cache_path=tmp_path / "client-b.db",
        expected_schema_revision="20260715_0006",
        writes_enabled=True,
        environment="development",
    )
    a = AtlasDataGateway(config_a, client=ApiTestAdapter(api), cache=CacheRepository(config_a.cache_path))
    b = AtlasDataGateway(config_b, client=ApiTestAdapter(api), cache=CacheRepository(config_b.cache_path))
    a.deep_refresh()
    b.deep_refresh()
    old_a = a.cache.get("machines", "WRITE-M1")
    old_b = b.cache.get("machines", "WRITE-M1")
    assert old_a["row_version"] == old_b["row_version"]
    changed = a.update_machine("WRITE-M1", {"machine_name": "Client A"}, old_a["row_version"])
    assert changed["machine_name"] == "Client A"
    with pytest.raises(ConcurrencyConflictError):
        b.update_machine("WRITE-M1", {"machine_name": "Client B stale"}, old_b["row_version"])
    assert b.cache.get("machines", "WRITE-M1")["machine_name"] != "Client B stale"
    b.refresh()
    assert b.cache.get("machines", "WRITE-M1")["machine_name"] == "Client A"
    before_history_ids = {item["event_id"] for item in b.cache.get_eoat_history("WRITE-EOAT")}
    current_eoat = a.cache.get("eoats", "WRITE-EOAT")
    a.update_eoat("WRITE-EOAT", {"display_name": "Client A History"}, current_eoat["row_version"])
    b.refresh()
    refreshed_history = b.cache.get_eoat_history("WRITE-EOAT")
    assert {item["event_id"] for item in refreshed_history} > before_history_ids
    assert refreshed_history[0]["event_type"] == "EOAT_UPDATED"
    rebuilt_history_ids = [item["event_id"] for item in refreshed_history]
    b.cache.path.unlink()
    b.deep_refresh()
    assert b.cache.get("machines", "WRITE-M1")["machine_name"] == "Client A"
    assert [item["event_id"] for item in b.cache.get_eoat_history("WRITE-EOAT")] == rebuilt_history_ids


def test_gateway_blocks_offline_writes_without_queueing(tmp_path):
    config = GatewayConfiguration(
        backend="mysql_api",
        cache_path=tmp_path / "offline.db",
        expected_schema_revision="20260715_0006",
        writes_enabled=True,
        environment="development",
    )
    gateway = AtlasDataGateway(config, client=OfflineAdapter(), cache=CacheRepository(config.cache_path))
    with pytest.raises(WriteBlockedError):
        gateway.create_eoat({"business_identifier": "OFFLINE-MUST-NOT-EXIST"})
    assert not config.cache_path.exists()


def test_server_success_survives_local_cache_refresh_failure(api, tmp_path):
    config = GatewayConfiguration(
        backend="mysql_api",
        cache_path=tmp_path / "fail-cache.db",
        expected_schema_revision="20260715_0006",
        writes_enabled=True,
        environment="development",
    )
    gateway = AtlasDataGateway(config, client=ApiTestAdapter(api), cache=FailingRefreshCache(config.cache_path))
    result = gateway.create_tool({"business_identifier": "CACHE-FAIL-T1"}, idempotency_key="cache-fail-create")
    assert result["business_identifier"] == "CACHE-FAIL-T1"
    assert result["cache_refresh_required"] is True
    assert api.get("/api/v1/tools/CACHE-FAIL-T1").status_code == 200


def test_database_unavailable_returns_normalized_503_without_write(api):
    def unavailable_session():
        raise OperationalError("SELECT 1", {}, Exception("simulated unavailable database"))
        yield

    app.dependency_overrides[get_write_session] = unavailable_session
    try:
        response = post(api, "/api/v1/eoats", {"business_identifier": "DB-DOWN"}, ENGINEER, "db-down")
    finally:
        app.dependency_overrides.pop(get_write_session, None)
    assert response.status_code == 503
    assert response.json()["error_code"] == "DATABASE_UNAVAILABLE"
    assert response.json()["retryable"] is True


def test_change_feed_cache_failure_does_not_advance_cursor(tmp_path, monkeypatch):
    cache = CacheRepository(tmp_path / "cursor.db")
    cache.initialize()
    before = cache.metadata()["last_change_cursor"]

    def fail_metadata(_connection, _values):
        raise OSError("simulated local apply failure")

    monkeypatch.setattr(cache, "_put_metadata", fail_metadata)
    with pytest.raises(OSError):
        cache.apply_change_cursor({"next_cursor": 9, "changes": [{"cursor": 9}]})
    assert cache.metadata()["last_change_cursor"] == before


def test_archived_development_user_cannot_write(api, monkeypatch):
    monkeypatch.setenv("EOAT_API_DEV_IDENTITIES", '{"dev.archived":"ENGINEER"}')
    first = post(
        api,
        "/api/v1/tools",
        {"business_identifier": "ARCHIVED-USER-FIRST"},
        {"X-EOAT-Identity": "dev.archived"},
        "archived-user-first",
    )
    assert first.status_code == 200
    factory = create_session_factory(migration=True)
    with factory() as session, session.begin():
        user = session.scalar(select(db.User).where(db.User.external_identity == "dev.archived"))
        user.is_active = False
    denied = post(
        api,
        "/api/v1/tools",
        {"business_identifier": "ARCHIVED-USER-DENIED"},
        {"X-EOAT-Identity": "dev.archived"},
        "archived-user-denied",
    )
    assert denied.status_code == 403 and denied.json()["error_code"] == "IDENTITY_INACTIVE"


def test_snapshot_query_count_is_bounded():
    factory = create_session_factory(migration=True)
    with factory() as session:
        statements = []

        def before_execute(_conn, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement)

        event.listen(session.bind, "before_cursor_execute", before_execute)
        try:
            snapshot = AtlasService(session).snapshot()
        finally:
            event.remove(session.bind, "before_cursor_execute", before_execute)
    assert snapshot.eoats and snapshot.machines and snapshot.tools
    assert len(statements) <= 40
