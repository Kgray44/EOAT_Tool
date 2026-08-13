from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from server.eoat_api.app import app
from server.eoat_api.database import models as db
from server.eoat_api.database.session import create_session_factory

pytestmark = pytest.mark.skipif(
    os.getenv("EOAT_DB_NAME") != "eoat_atlas_test",
    reason="Phase 4 danger-operation tests require EOAT_DB_NAME=eoat_atlas_test",
)

RUN = uuid4().hex[:10]
REHEARSAL_SECRET = "phase4-integration-rehearsal-secret"


@pytest.fixture(scope="module", autouse=True)
def phase4_environment():
    previous = {
        key: os.environ.get(key)
        for key in (
            "EOAT_API_WRITES_ENABLED",
            "EOAT_API_ENVIRONMENT",
            "EOAT_API_ADMIN_REHEARSAL_SECRET",
        )
    }
    os.environ["EOAT_API_WRITES_ENABLED"] = "true"
    os.environ["EOAT_API_ENVIRONMENT"] = "development"
    os.environ["EOAT_API_ADMIN_REHEARSAL_SECRET"] = REHEARSAL_SECRET
    yield
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


@pytest.fixture(scope="module")
def fixture_namespace():
    recovery = Path(os.environ.get("EOAT_PHASE4_TEST_RECOVERY_POINT", ""))
    assert recovery.is_file(), "A tested EOAT_PHASE4_TEST_RECOVERY_POINT is required for the dangerous-operation rehearsal."
    namespace = f"phase4-{RUN}"
    with create_session_factory(migration=True)() as session, session.begin():
        session.add_all(
            [
                db.AdminOperationFixture(
                    fixture_namespace=namespace,
                    fixture_key="one",
                    payload_json={"source": "isolated Phase 4 acceptance"},
                ),
                db.AdminOperationFixture(
                    fixture_namespace=namespace,
                    fixture_key="two",
                    payload_json={"source": "isolated Phase 4 acceptance"},
                ),
            ]
        )
    return namespace


@pytest.fixture
def api():
    with TestClient(app, raise_server_exceptions=False) as client:
        login = client.post(
            "/api/v1/admin/session/rehearsal",
            json={"identity": "dev.admin", "rehearsal_secret": REHEARSAL_SECRET},
        )
        assert login.status_code == 200, login.text
        yield client, {"X-EOAT-CSRF-Token": login.json()["csrf_token"]}


def test_phase4_controlled_evidence_and_fixture_recovery_are_real_mysql_audited(api, fixture_namespace):
    """Exercise only disposable rows in the isolated test schema.

    This test intentionally relies on the runtime role rather than the
    migrator.  That proves the deployed application account has the minimum
    DML it needs for the new durable operation evidence tables.
    """
    client, csrf = api
    diagnostics = client.get("/api/v1/admin/diagnostics", headers={"X-EOAT-Identity": "dev.admin"})
    assert diagnostics.status_code == 200, diagnostics.text
    assert {"api", "database", "schema", "audit"}.issubset(diagnostics.json()["by_subsystem"])

    integrity = client.post("/api/v1/admin/integrity/scans", json={"reason": "Phase 4 test"}, headers=csrf)
    assert integrity.status_code == 200, integrity.text
    assert integrity.json()["status"] == "COMPLETED"

    exported = client.post("/api/v1/admin/audit/exports", json={"format": "json", "filters": {}}, headers=csrf)
    assert exported.status_code == 200, exported.text
    assert exported.headers["X-EOAT-Export-Checksum"]
    assert b'"manifest"' in exported.content

    bundle = client.post(
        "/api/v1/admin/support-bundles",
        json={"sections": ["health", "integrity", "release"]},
        headers=csrf,
    )
    assert bundle.status_code == 200, bundle.text
    assert bundle.headers["X-EOAT-Support-Checksum"]

    preview = client.post(
        "/api/v1/admin/danger-zone/fixture-recovery/preview",
        json={"fixture_namespace": fixture_namespace},
        headers=csrf,
    )
    assert preview.status_code == 200, preview.text
    preview_body = preview.json()
    denied = client.post(
        "/api/v1/admin/danger-zone/fixture-recovery/commit",
        json={
            "preview_reference": preview_body["preview_reference"],
            "confirmation": preview_body["typed_confirmation"],
            "reason": "Verify server-side step-up denial",
        },
        headers={**csrf, "Idempotency-Key": f"phase4-denied-{RUN}"},
    )
    assert denied.status_code == 200, denied.text
    assert denied.json()["status"] == "DENIED"

    step_up = client.post(
        "/api/v1/admin/danger-zone/fixture-recovery/step-up",
        json={"rehearsal_step_up_secret": REHEARSAL_SECRET},
        headers=csrf,
    )
    assert step_up.status_code == 200, step_up.text
    committed_preview = client.post(
        "/api/v1/admin/danger-zone/fixture-recovery/preview",
        json={"fixture_namespace": fixture_namespace},
        headers=csrf,
    )
    assert committed_preview.status_code == 200, committed_preview.text
    commit_body = committed_preview.json()
    committed = client.post(
        "/api/v1/admin/danger-zone/fixture-recovery/commit",
        json={
            "preview_reference": commit_body["preview_reference"],
            "confirmation": commit_body["typed_confirmation"],
            "reason": "Remove only named Phase 4 test fixtures",
        },
        headers={**csrf, "Idempotency-Key": f"phase4-commit-{RUN}"},
    )
    assert committed.status_code == 200, committed.text
    assert committed.json()["status"] == "COMPLETED"
    assert committed.json()["removed_count"] == 2

    with create_session_factory(migration=True)() as session:
        remaining = session.scalar(
            select(func.count(db.AdminOperationFixture.id)).where(
                db.AdminOperationFixture.fixture_namespace == fixture_namespace
            )
        )
        assert remaining == 0
        actions = set(
            session.scalars(
                select(db.AuditEvent.action).where(
                    db.AuditEvent.operation.like("admin.danger.fixture-recovery%")
                )
            ).all()
        )
        assert {"DANGER_ATTEMPT", "DANGER_CONFIRMED", "DANGER_STARTED", "DANGER_SUCCEEDED"}.issubset(actions)
