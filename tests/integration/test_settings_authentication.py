from __future__ import annotations

import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from server.eoat_api.app import app
from server.eoat_api.authentication.identity_models import ProviderHealth
from server.eoat_api.authentication.providers.development import DevelopmentAuthenticationProvider
from server.eoat_api.database import models as db
from server.eoat_api.database.session import create_session_factory

pytestmark = pytest.mark.skipif(
    os.getenv("EOAT_DB_NAME") != "eoat_atlas_test",
    reason="Settings authentication integration tests require EOAT_DB_NAME=eoat_atlas_test",
)


@pytest.fixture(scope="module")
def api():
    with TestClient(app) as client:
        yield client


def test_normal_application_endpoints_do_not_require_user_authentication(api) -> None:
    config = api.get("/api/v1/auth/config")
    home = api.get("/api/v1/home-summary")

    assert config.status_code == 200
    assert config.json()["startup_authentication_required"] is False
    assert config.json()["ordinary_application_access_requires_login"] is False
    assert home.status_code == 200


def test_normal_application_write_does_not_require_user_authentication(api) -> None:
    identifier = f"NO-LOGIN-{uuid4().hex[:10]}"
    response = api.post(
        "/api/v1/eoats",
        headers={"Idempotency-Key": f"no-login-{uuid4()}"},
        json={"business_identifier": identifier, "display_name": "Unsigned-in workflow validation"},
    )

    assert response.status_code == 200
    assert response.json()["business_identifier"] == identifier


def test_settings_write_authorization_distinguishes_401_and_403(api) -> None:
    missing = api.put("/api/v1/settings/test.authorization", json={"value": "missing"})
    viewer_login = api.post("/api/v1/auth/development/login", json={"identity": "dev.viewer"})
    viewer_token = viewer_login.json()["access_token"]
    denied = api.put(
        "/api/v1/settings/test.authorization",
        headers={"Authorization": f"Bearer {viewer_token}"},
        json={"value": "denied"},
    )

    assert missing.status_code == 401
    assert missing.json()["error_code"] == "AUTHENTICATION_REQUIRED"
    assert viewer_login.status_code == 200
    assert denied.status_code == 403
    assert denied.json()["error_code"] == "PERMISSION_DENIED"


def test_settings_reads_are_anonymous_and_authorized_writes_succeed(api) -> None:
    setting_key = f"phase10.validation.{uuid4().hex}"
    initial = api.get("/api/v1/settings")
    login = api.post("/api/v1/auth/development/login", json={"identity": "dev.admin"})
    token = login.json()["access_token"]
    written = api.put(
        f"/api/v1/settings/{setting_key}",
        headers={"Authorization": f"Bearer {token}"},
        json={"value": {"enabled": True}, "description": "Phase 10 authorization validation"},
    )
    anonymous_read = api.get("/api/v1/settings")

    assert initial.status_code == 200
    assert initial.json()["authentication_required"] is False
    assert written.status_code == 200
    assert written.json()["value"] == {"enabled": True}
    assert any(item["key"] == setting_key for item in anonymous_read.json()["items"])


def test_administrator_session_is_memory_token_ready_and_revocable(api) -> None:
    login = api.post("/api/v1/auth/development/login", json={"identity": "dev.admin"})
    assert login.status_code == 200
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    allowed = api.post(
        "/api/v1/settings/authorization/check",
        headers=headers,
        json={"permission": "settings.edit", "operation": "test"},
    )
    logout = api.post("/api/v1/auth/logout", headers=headers)
    revoked = api.post(
        "/api/v1/settings/authorization/check",
        headers=headers,
        json={"permission": "settings.edit", "operation": "test"},
    )

    assert allowed.status_code == 200
    assert allowed.json()["authorized"] is True
    assert logout.status_code == 200
    assert revoked.status_code == 401
    assert revoked.json()["error_code"] == "SESSION_INVALID"


def test_permission_loss_relocks_settings_server_side(api) -> None:
    login = api.post("/api/v1/auth/development/login", json={"identity": "dev.admin"})
    token = login.json()["access_token"]
    factory = create_session_factory(migration=False)
    with factory() as session, session.begin():
        administrator_role = session.scalar(select(db.Role).where(db.Role.role_code == "ADMINISTRATOR"))
        administrator_role.is_active = False
    try:
        denied = api.post(
            "/api/v1/settings/authorization/check",
            headers={"Authorization": f"Bearer {token}"},
            json={"permission": "settings.edit", "operation": "permission-loss-test"},
        )
    finally:
        with factory() as session, session.begin():
            administrator_role = session.scalar(select(db.Role).where(db.Role.role_code == "ADMINISTRATOR"))
            administrator_role.is_active = True

    assert denied.status_code == 403
    assert denied.json()["error_code"] == "PERMISSION_DENIED"


def test_provider_outage_relocks_settings_without_blocking_normal_use(api, monkeypatch) -> None:
    login = api.post("/api/v1/auth/development/login", json={"identity": "dev.admin"})
    token = login.json()["access_token"]
    monkeypatch.setattr(
        DevelopmentAuthenticationProvider,
        "health_check",
        lambda self: ProviderHealth("development", True, False, False, "simulated provider outage"),
    )

    denied = api.post(
        "/api/v1/settings/authorization/check",
        headers={"Authorization": f"Bearer {token}"},
        json={"permission": "settings.edit", "operation": "provider-outage-test"},
    )
    ordinary = api.get("/api/v1/home-summary")

    assert denied.status_code == 503
    assert denied.json()["error_code"] == "AUTH_PROVIDER_UNAVAILABLE"
    assert ordinary.status_code == 200
