from __future__ import annotations

import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from server.eoat_api.app import app

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
    missing = api.post(
        "/api/v1/settings/authorization/check",
        json={"permission": "settings.edit", "operation": "test"},
    )
    denied = api.post("/api/v1/auth/development/login", json={"identity": "dev.viewer"})

    assert missing.status_code == 401
    assert missing.json()["error_code"] == "AUTHENTICATION_REQUIRED"
    assert denied.status_code == 403
    assert denied.json()["error_code"] == "SETTINGS_ACCESS_DENIED"


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
