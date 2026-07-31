from __future__ import annotations

import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from server.eoat_api.app import app
from server.eoat_api.authentication.identity_models import ProviderHealth
from server.eoat_api.authentication.providers.development import DevelopmentAuthenticationProvider
from server.eoat_api.authentication.routes import _CSRF_COOKIE, _SESSION_COOKIE
from server.eoat_api.database import models as db
from server.eoat_api.database.session import create_session_factory
from tests.fixtures.mysql_sanctioned import reset_and_load_sanctioned_fixture

pytestmark = pytest.mark.skipif(
    os.getenv("EOAT_DB_NAME") != "eoat_atlas_test",
    reason="Settings authentication integration tests require EOAT_DB_NAME=eoat_atlas_test",
)


@pytest.fixture(scope="module", autouse=True)
def sanctioned_database():
    reset_and_load_sanctioned_fixture()


@pytest.fixture(scope="module", autouse=True)
def explicit_development_write_environment():
    values = {"EOAT_API_ENVIRONMENT": "development", "EOAT_API_WRITES_ENABLED": "true"}
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


def csrf_headers(api: TestClient) -> dict[str, str]:
    return {"X-EOAT-CSRF": api.cookies.get("eoat_atlas_settings_csrf", "")}


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
    setting_key = "data_loading.refresh_on_launch"
    missing = api.put(f"/api/v1/settings/{setting_key}", json={"value": False})
    viewer_login = api.post("/api/v1/auth/development/login", json={"identity": "dev.viewer"})
    denied = api.put(
        f"/api/v1/settings/{setting_key}",
        headers=csrf_headers(api),
        json={"value": False},
    )

    assert missing.status_code == 401
    assert missing.json()["error_code"] == "AUTHENTICATION_REQUIRED"
    assert viewer_login.status_code == 200
    assert denied.status_code == 403
    assert denied.json()["error_code"] == "PERMISSION_DENIED"


def test_settings_reads_are_anonymous_and_authorized_writes_succeed(api) -> None:
    setting_key = "data_loading.manual_refresh_only"
    initial = api.get("/api/v1/settings")
    login = api.post("/api/v1/auth/development/login", json={"identity": "dev.admin"})
    written = api.put(
        f"/api/v1/settings/{setting_key}",
        headers=csrf_headers(api),
        json={"value": True, "description": "Settings authorization validation"},
    )
    anonymous_read = api.get("/api/v1/settings")

    assert initial.status_code == 200
    assert initial.json()["authentication_required"] is False
    assert written.status_code == 200
    assert written.json()["value"] is True
    assert any(item["key"] == setting_key for item in anonymous_read.json()["items"])


def test_settings_danger_actions_require_typed_confirmation_and_preserve_operational_data(api) -> None:
    login = api.post("/api/v1/auth/development/login", json={"identity": "dev.admin"})
    headers = csrf_headers(api)
    key = "data_loading.manual_refresh_only"
    assert api.put(f"/api/v1/settings/{key}", headers=headers, json={"value": True}).status_code == 200

    rejected = api.post(
        "/api/v1/settings/actions/reset-section",
        headers=headers,
        json={"section": "refresh_cache", "confirmation": "reset"},
    )
    reset = api.post(
        "/api/v1/settings/actions/reset-section",
        headers=headers,
        json={"section": "refresh_cache", "confirmation": "RESET SECTION"},
    )
    set_defaults = api.post(
        "/api/v1/settings/actions/set-defaults",
        headers=headers,
        json={"confirmation": "SET DEFAULTS"},
    )
    factory = api.post(
        "/api/v1/settings/actions/factory-reset",
        headers=headers,
        json={"confirmation": "FACTORY RESET"},
    )

    assert rejected.status_code == 422
    assert reset.status_code == 200
    assert reset.json()["action"] == "reset-section"
    assert set_defaults.status_code == 200
    assert factory.status_code == 200
    values = {item["key"]: item["value"] for item in api.get("/api/v1/settings").json()["items"]}
    assert key not in values


def test_administrator_session_is_cookie_backed_and_revocable(api) -> None:
    login = api.post("/api/v1/auth/development/login", json={"identity": "dev.admin"})
    assert login.status_code == 200
    headers = csrf_headers(api)
    session_token = api.cookies.get(_SESSION_COOKIE)
    csrf_token = api.cookies.get(_CSRF_COOKIE)
    assert session_token and csrf_token

    allowed = api.post(
        "/api/v1/settings/authorization/check",
        headers=headers,
        json={"permission": "settings.edit", "operation": "test"},
    )
    logout = api.post("/api/v1/auth/logout", headers=headers)
    no_cookie = api.post(
        "/api/v1/settings/authorization/check",
        headers=headers,
        json={"permission": "settings.edit", "operation": "test"},
    )
    stale_cookie = api.post(
        "/api/v1/settings/authorization/check",
        headers={
            "X-EOAT-CSRF": csrf_token,
            "Cookie": f"{_SESSION_COOKIE}={session_token}; {_CSRF_COOKIE}={csrf_token}",
        },
        json={"permission": "settings.edit", "operation": "test"},
    )

    assert allowed.status_code == 200
    assert allowed.json()["authorized"] is True
    assert logout.status_code == 200
    assert no_cookie.status_code == 401
    assert no_cookie.json()["error_code"] == "AUTHENTICATION_REQUIRED"
    assert stale_cookie.status_code == 401
    assert stale_cookie.json()["error_code"] == "SESSION_INVALID"


def test_permission_loss_relocks_settings_server_side(api) -> None:
    login = api.post("/api/v1/auth/development/login", json={"identity": "dev.admin"})
    factory = create_session_factory(migration=False)
    with factory() as session, session.begin():
        administrator_role = session.scalar(select(db.Role).where(db.Role.role_code == "ADMINISTRATOR"))
        administrator_role.is_active = False
    try:
        denied = api.post(
            "/api/v1/settings/authorization/check",
            headers=csrf_headers(api),
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
    monkeypatch.setattr(
        DevelopmentAuthenticationProvider,
        "health_check",
        lambda self: ProviderHealth("development", True, False, False, "simulated provider outage"),
    )

    denied = api.post(
        "/api/v1/settings/authorization/check",
        headers=csrf_headers(api),
        json={"permission": "settings.edit", "operation": "provider-outage-test"},
    )
    ordinary = api.get("/api/v1/home-summary")

    assert denied.status_code == 503
    assert denied.json()["error_code"] == "AUTH_PROVIDER_UNAVAILABLE"
    assert ordinary.status_code == 200
