"""Application-scope authorization through real EOAT sessions and test data only."""

from __future__ import annotations

import os
from base64 import b64encode
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from server.eoat_api.app import app
from server.eoat_api.database import models as db
from server.eoat_api.database.session import create_session_factory
from tests.fixtures.mysql_sanctioned import FIXTURE_SOURCE, reset_and_load_sanctioned_fixture

pytestmark = pytest.mark.skipif(
    os.getenv("EOAT_DB_NAME") != "eoat_atlas_test",
    reason="Application authorization integration tests require EOAT_DB_NAME=eoat_atlas_test",
)


@pytest.fixture(scope="module", autouse=True)
def sanctioned_database():
    reset_and_load_sanctioned_fixture()


@pytest.fixture(scope="module", autouse=True)
def application_authentication_environment():
    values = {
        "EOAT_API_ENVIRONMENT": "development",
        "EOAT_API_WRITES_ENABLED": "true",
        "EOAT_AUTH_PROVIDER": "development",
        "EOAT_AUTH_SCOPE": "application",
    }
    previous = {name: os.environ.get(name) for name in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


@pytest.fixture(scope="module")
def api():
    with TestClient(app) as client:
        yield client


def _login(api: TestClient, identity: str) -> tuple[dict[str, str], dict]:
    response = api.post("/api/v1/auth/development/login", json={"identity": identity})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}, response.json()


def _document_payload(tmp_path) -> dict:
    source = tmp_path / "controlled-document.txt"
    source.write_text("controlled test document", encoding="utf-8")
    with create_session_factory(migration=True)() as session:
        eoat_id = session.scalar(
            select(db.EOAT.id)
            .where(db.EOAT.source_system == FIXTURE_SOURCE, db.EOAT.is_active.is_(True))
            .order_by(db.EOAT.id)
        )
    assert eoat_id is not None
    return {
        "document_type": "document",
        "title": "Application authorization test",
        "storage_path": str(source),
        "entity_type": "eoat",
        "entity_id": eoat_id,
    }


def test_session_permissions_are_concrete_and_least_privilege(api):
    _viewer_headers, viewer = _login(api, "dev.viewer")
    _technician_headers, technician = _login(api, "dev.technician")
    _engineer_headers, engineer = _login(api, "dev.engineer")
    _administrator_headers, administrator = _login(api, "dev.admin")

    assert viewer["scope"] == "application" and viewer["permissions"] == []
    assert "installation.write" in technician["permissions"]
    assert "asset.write" not in technician["permissions"]
    assert "document.write" not in technician["permissions"]
    assert {"asset.write", "document.write"}.issubset(engineer["permissions"])
    assert "settings.edit" not in engineer["permissions"]
    assert {"asset.write", "document.write", "settings.edit"}.issubset(administrator["permissions"])


def test_asset_document_and_session_authorization_are_enforced_server_side(api, tmp_path):
    engineer_headers, _engineer = _login(api, "dev.engineer")
    viewer_headers, _viewer = _login(api, "dev.viewer")
    technician_headers, _technician = _login(api, "dev.technician")
    identifier = f"AUTHZ-{uuid4().hex[:10]}"

    permitted_asset = api.post("/api/v1/eoats", headers={**engineer_headers, "Idempotency-Key": f"asset-{uuid4()}"}, json={"business_identifier": identifier, "display_name": "Authorized engineering write"})
    denied_asset = api.post("/api/v1/eoats", headers={**viewer_headers, "Idempotency-Key": f"viewer-{uuid4()}"}, json={"business_identifier": f"DENIED-{uuid4().hex[:10]}"})
    unauthenticated = api.post("/api/v1/eoats", headers={"Idempotency-Key": f"anonymous-{uuid4()}"}, json={"business_identifier": f"ANON-{uuid4().hex[:10]}"})
    permitted_document = api.post("/api/v1/documents", headers={**engineer_headers, "Idempotency-Key": f"document-{uuid4()}"}, json=_document_payload(tmp_path))
    denied_document = api.post("/api/v1/documents", headers={**technician_headers, "Idempotency-Key": f"tech-document-{uuid4()}"}, json=_document_payload(tmp_path))

    assert permitted_asset.status_code == 200
    assert denied_asset.status_code == 403 and denied_asset.json()["error_code"] == "PERMISSION_DENIED"
    assert unauthenticated.status_code in {401, 403}
    assert permitted_document.status_code == 200
    assert denied_document.status_code == 403 and denied_document.json()["error_code"] == "PERMISSION_DENIED"
    with create_session_factory(migration=True)() as session:
        actor = session.scalar(select(db.User).where(db.User.external_subject == "dev.engineer"))
        audit = session.scalar(select(db.ChangeAuditLog).where(db.ChangeAuditLog.entity_type == "eoat", db.ChangeAuditLog.entity_id == permitted_asset.json()["id"], db.ChangeAuditLog.success.is_(True)))
    assert actor is not None and audit is not None and audit.actor_user_id == actor.id


def test_logout_invalidates_session_before_mutation(api):
    headers, _payload = _login(api, "dev.engineer")
    assert api.post("/api/v1/auth/logout", headers=headers).status_code == 200
    rejected = api.post("/api/v1/eoats", headers={**headers, "Idempotency-Key": f"revoked-{uuid4()}"}, json={"business_identifier": f"REVOKED-{uuid4().hex[:10]}"})
    assert rejected.status_code == 401
    assert rejected.json()["error_code"] == "SESSION_INVALID"


def test_cookie_session_requires_csrf_and_records_the_authenticated_actor(api):
    headers, session = _login(api, "dev.engineer")
    token = headers["Authorization"].removeprefix("Bearer ")
    with create_session_factory(migration=True)() as database:
        record = database.scalar(
            select(db.EOAT)
            .where(db.EOAT.source_system == FIXTURE_SOURCE, db.EOAT.is_active.is_(True))
            .order_by(db.EOAT.id)
        )
        assert record is not None
        identifier, row_version = record.business_identifier, record.row_version
    cookie = f"eoat_atlas_session={token}; eoat_atlas_csrf=test-csrf-token"
    missing_csrf = api.patch(
        f"/api/v1/eoats/{identifier}",
        headers={"Cookie": cookie},
        json={"expected_row_version": row_version, "display_name": "CSRF must fail"},
    )
    accepted = api.patch(
        f"/api/v1/eoats/{identifier}",
        headers={"Cookie": cookie, "X-EOAT-CSRF-Token": "test-csrf-token"},
        json={"expected_row_version": row_version, "display_name": "CSRF-protected browser update"},
    )
    assert missing_csrf.status_code == 403
    assert missing_csrf.json()["error_code"] == "CSRF_VALIDATION_FAILED"
    assert accepted.status_code == 200
    with create_session_factory(migration=True)() as database:
        engineer = database.scalar(select(db.User).where(db.User.external_subject == session["identity"]["external_subject"]))
        audit = database.scalar(
            select(db.ChangeAuditLog)
            .where(
                db.ChangeAuditLog.entity_type == "eoat",
                db.ChangeAuditLog.entity_id == accepted.json()["id"],
                db.ChangeAuditLog.success.is_(True),
            )
            .order_by(db.ChangeAuditLog.id.desc())
        )
    assert engineer is not None and audit is not None and audit.actor_user_id == engineer.id


def test_engineer_can_update_machine_tool_and_eoat_with_auditable_identity(api):
    headers, session = _login(api, "dev.engineer")
    with create_session_factory(migration=True)() as database:
        machine = database.scalar(select(db.Machine).where(db.Machine.is_active.is_(True)).order_by(db.Machine.id))
        tool = database.scalar(select(db.Tool).where(db.Tool.is_active.is_(True)).order_by(db.Tool.id))
        eoat = database.scalar(select(db.EOAT).where(db.EOAT.is_active.is_(True)).order_by(db.EOAT.id))
        assert machine is not None and tool is not None and eoat is not None
        records = [
            ("machine", machine.machine_number, machine.row_version, {"machine_name": "Browser machine update"}),
            ("tool", tool.business_identifier, tool.row_version, {"display_name": "Browser tool update"}),
            ("eoat", eoat.business_identifier, eoat.row_version, {"display_name": "Browser EOAT update"}),
        ]
    results = []
    for entity_type, identifier, row_version, change in records:
        response = api.patch(
            f"/api/v1/{entity_type}s/{identifier}",
            headers=headers,
            json={"expected_row_version": row_version, **change},
        )
        assert response.status_code == 200
        assert response.json()["row_version"] == row_version + 1
        results.append((entity_type, response.json()["id"]))
    with create_session_factory(migration=True)() as database:
        engineer = database.scalar(select(db.User).where(db.User.external_subject == session["identity"]["external_subject"]))
        assert engineer is not None
        for entity_type, entity_id in results:
            audit = database.scalar(
                select(db.ChangeAuditLog)
                .where(
                    db.ChangeAuditLog.entity_type == entity_type,
                    db.ChangeAuditLog.entity_id == entity_id,
                    db.ChangeAuditLog.success.is_(True),
                )
                .order_by(db.ChangeAuditLog.id.desc())
            )
            assert audit is not None and audit.actor_user_id == engineer.id


def test_engineer_can_create_compatibility_but_invalid_status_is_rejected(api):
    headers, session = _login(api, "dev.engineer")
    identifier = f"COMPAT-{uuid4().hex[:10]}"
    created = api.post(
        "/api/v1/eoats",
        headers={**headers, "Idempotency-Key": f"compat-eoat-{uuid4()}"},
        json={"business_identifier": identifier, "display_name": "Compatibility browser fixture"},
    )
    assert created.status_code == 200
    with create_session_factory(migration=True)() as database:
        machine = database.scalar(select(db.Machine).where(db.Machine.is_active.is_(True)).order_by(db.Machine.id))
        status = database.scalar(select(db.CompatibilityStatus.code).where(db.CompatibilityStatus.is_active.is_(True)).order_by(db.CompatibilityStatus.sort_order))
        assert machine is not None and status is not None
    invalid = api.post(
        "/api/v1/compatibility/eoat-machine",
        headers=headers,
        json={"eoat_identifier": identifier, "machine_number": machine.machine_number, "compatibility_status": "not-a-real-status", "effective_from": "2026-08-10T00:00:00Z"},
    )
    accepted = api.post(
        "/api/v1/compatibility/eoat-machine",
        headers=headers,
        json={"eoat_identifier": identifier, "machine_number": machine.machine_number, "compatibility_status": status, "effective_from": "2026-08-10T00:00:00Z", "reason": "Browser engineering review"},
    )
    assert invalid.status_code == 422
    assert accepted.status_code == 200
    with create_session_factory(migration=True)() as database:
        engineer = database.scalar(select(db.User).where(db.User.external_subject == session["identity"]["external_subject"]))
        audit = database.scalar(
            select(db.ChangeAuditLog)
            .where(
                db.ChangeAuditLog.entity_type == "eoat_machine_compatibility",
                db.ChangeAuditLog.entity_id == accepted.json()["id"],
                db.ChangeAuditLog.success.is_(True),
            )
            .order_by(db.ChangeAuditLog.id.desc())
        )
    assert engineer is not None and audit is not None and audit.actor_user_id == engineer.id


def test_engineer_can_upload_browser_media_without_a_storage_path_exposure(api, tmp_path, monkeypatch):
    headers, session = _login(api, "dev.engineer")
    upload_root = tmp_path / "controlled-browser-media"
    upload_root.mkdir()
    monkeypatch.setenv("EOAT_WEB_UPLOAD_ROOT", str(upload_root))
    monkeypatch.setenv("EOAT_DOCUMENT_ROOTS", str(upload_root))
    monkeypatch.setenv("EOAT_WEB_CONTENT_ROOTS", str(upload_root))
    with create_session_factory(migration=True)() as database:
        eoat = database.scalar(select(db.EOAT).where(db.EOAT.is_active.is_(True)).order_by(db.EOAT.id))
        assert eoat is not None
        identifier = eoat.business_identifier
    response = api.post(
        "/api/v1/web-media/upload",
        headers=headers,
        json={
            "entity_type": "eoat",
            "entity_identifier": identifier,
            "title": "Browser upload acceptance",
            "document_type": "document",
            "media_kind": "document",
            "file_name": "browser-proof.txt",
            "content_base64": b64encode(b"browser upload acceptance").decode("ascii"),
            "mime_type": "text/plain",
        },
    )
    assert response.status_code == 200
    assert "storage_path" not in response.json()
    assert response.json()["file_name"].endswith("browser-proof.txt")
    with create_session_factory(migration=True)() as database:
        engineer = database.scalar(select(db.User).where(db.User.external_subject == session["identity"]["external_subject"]))
        document = database.scalar(select(db.Document).where(db.Document.document_uuid == response.json()["document_uuid"]))
        audit = database.scalar(
            select(db.ChangeAuditLog)
            .where(
                db.ChangeAuditLog.entity_type == "document",
                db.ChangeAuditLog.entity_id == document.id if document else -1,
                db.ChangeAuditLog.success.is_(True),
            )
            .order_by(db.ChangeAuditLog.id.desc())
        )
    assert document is not None and document.storage_path.startswith(str(upload_root))
    assert engineer is not None and audit is not None and audit.actor_user_id == engineer.id
