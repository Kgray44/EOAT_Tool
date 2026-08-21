from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from starlette.requests import Request

from server.eoat_api.admin import mutation_service
from server.eoat_api.app import app
from server.eoat_api.corporate_auth import ADMINISTRATOR_GROUP_IDENTIFIER
from server.eoat_api.corporate_auth_routes import _cookie_secure, corporate_session_service
from server.eoat_api.corporate_sessions import (
    CorporateAuthenticationFailure,
    CorporateSessionService,
    DirectoryIdentity,
    corporate_csrf_valid,
    normalize_principal,
)
from server.eoat_api.corporate_users import (
    access_state,
    change_explicit_access,
    corporate_user_for_user,
    preview_explicit_access,
)
from server.eoat_api.database import models as db
from server.eoat_api.database.session import get_runtime_session, get_write_session
from server.eoat_api.errors import APIError
from server.eoat_api.security import ROLE_PERMISSIONS, ActorContext, actor_context, corporate_session_actor


class FakeAuthenticator:
    def authenticate(self, principal: str, password: str) -> DirectoryIdentity:
        assert principal == "kgray@GWPLASTICS.COM"
        assert password == "not-persisted"
        return DirectoryIdentity(
            username="kgray",
            upn="KGray@GWPLASTICS.COM",
            display_name="K Gray",
            groups=(ADMINISTRATOR_GROUP_IDENTIFIER,),
        )


class UnavailableAuthenticator:
    """Safe application-side stand-in for a provider transport failure."""

    def authenticate(self, _principal: str, _password: str) -> DirectoryIdentity:
        raise CorporateAuthenticationFailure("Authentication is unavailable.", reason_code="KERBEROS_UNAVAILABLE")


def _configure(monkeypatch) -> None:
    monkeypatch.setenv("EOAT_KERBEROS_REALM", "GWPLASTICS.COM")
    monkeypatch.setenv("EOAT_KERBEROS_BASE_DN", "DC=gwplastics,DC=com")
    monkeypatch.setenv("EOAT_KERBEROS_CACHE_DIRECTORY", "/not-used-by-fake")
    monkeypatch.setenv("EOAT_KERBEROS_LOGIN_TIMEOUT_SECONDS", "15")
    monkeypatch.setenv("EOAT_KERBEROS_MIN_SASL_SSF", "256")
    monkeypatch.setenv("EOAT_AUTH_SESSION_MINUTES", "15")


def _engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def _sqlite_utc_timestamp(connection, _record):
        connection.create_function(
            "UTC_TIMESTAMP", 1, lambda _precision: datetime.now(timezone.utc).replace(tzinfo=None).isoformat(" ")
        )

    with engine.begin() as connection:
        connection.exec_driver_sql(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT, external_identity TEXT UNIQUE,
                username TEXT NOT NULL UNIQUE, display_name TEXT NOT NULL, email TEXT,
                authentication_provider TEXT, last_login_at DATETIME,
                created_by_user_id INTEGER, updated_by_user_id INTEGER, row_version INTEGER DEFAULT 1,
                is_active BOOLEAN DEFAULT 1, archived_at DATETIME, archived_by_user_id INTEGER,
                source_system TEXT DEFAULT 'eoat_atlas', source_import_batch_id INTEGER,
                created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL
            )
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE roles (
                id INTEGER PRIMARY KEY AUTOINCREMENT, role_code TEXT UNIQUE NOT NULL,
                role_name TEXT NOT NULL, description TEXT, is_active BOOLEAN NOT NULL DEFAULT 1,
                created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL
            )
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE external_group_role_mappings (
                id INTEGER PRIMARY KEY AUTOINCREMENT, provider TEXT NOT NULL,
                external_group_identifier TEXT NOT NULL, role_code TEXT NOT NULL,
                explicit_deny BOOLEAN DEFAULT 0, is_active BOOLEAN DEFAULT 1, row_version INTEGER NOT NULL DEFAULT 1,
                created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL
            )
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE corporate_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_uuid TEXT UNIQUE NOT NULL,
                user_id INTEGER UNIQUE NOT NULL, provider TEXT NOT NULL,
                canonical_identity TEXT NOT NULL, display_name TEXT NOT NULL,
                first_successful_sign_in_at DATETIME NOT NULL,
                last_successful_sign_in_at DATETIME NOT NULL, sign_in_count INTEGER NOT NULL,
                explicit_role_code TEXT, explicit_denied BOOLEAN DEFAULT 0,
                access_reason TEXT, access_changed_at DATETIME,
                access_changed_by_user_id INTEGER, created_by_user_id INTEGER,
                updated_by_user_id INTEGER, row_version INTEGER DEFAULT 1,
                is_active BOOLEAN DEFAULT 1, archived_at DATETIME,
                archived_by_user_id INTEGER, source_system TEXT DEFAULT 'corporate_auth',
                source_import_batch_id INTEGER, created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            )
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE corporate_authentication_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT, session_reference TEXT UNIQUE NOT NULL,
                token_hash TEXT UNIQUE NOT NULL, csrf_token_hash TEXT NOT NULL, user_id INTEGER NOT NULL,
                provider TEXT NOT NULL, roles_json JSON NOT NULL, authenticated_at DATETIME NOT NULL,
                issued_at DATETIME NOT NULL, expires_at DATETIME NOT NULL, last_seen_at DATETIME,
                revoked_at DATETIME, revoke_reason TEXT, authorization_groups_json JSON,
                fresh_authenticated_at DATETIME, fresh_auth_operation TEXT,
                fresh_auth_risk_class TEXT, fresh_auth_expires_at DATETIME
            )
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE corporate_authentication_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, event_uuid TEXT UNIQUE NOT NULL,
                event_type TEXT NOT NULL, occurred_at DATETIME NOT NULL, result TEXT NOT NULL,
                user_id INTEGER, provider TEXT, reason_code TEXT
            )
            """
        )
    return engine


def test_group_policy_editor_service_validates_audits_and_versions(monkeypatch):
    engine = _engine()
    session = Session(engine)

    class AuditWriter:
        def write_change(self, *_args, **_kwargs):
            return SimpleNamespace(event_id="group-policy-audit")

    monkeypatch.setattr(mutation_service, "AuditEventWriter", AuditWriter)
    now = datetime.now(timezone.utc)
    actor = ActorContext(1, "kgray", "K Gray", "ADMINISTRATOR", "request-1", None, None)
    try:
        session.add_all(
            [
                db.Role(role_code="VIEWER", role_name="Viewer", is_active=True, created_at=now, updated_at=now),
                db.Role(role_code="ENGINEER", role_name="Engineer", is_active=True, created_at=now, updated_at=now),
                db.Role(
                    role_code="ADMINISTRATOR",
                    role_name="Administrator",
                    is_active=True,
                    created_at=now,
                    updated_at=now,
                ),
            ]
        )
        session.flush()
        created = mutation_service.create_group_policy_governed(
            session, actor, "CN=EOAT Engineering", "VIEWER", "Initial governed policy"
        )
        assert created["policy"]["status"] == "active"
        assert created["audit_event_id"] == "group-policy-audit"
        policy_id = created["policy"]["id"]
        with pytest.raises(APIError, match="already has") as duplicate:
            mutation_service.create_group_policy_governed(
                session, actor, "CN=EOAT Engineering", "VIEWER", "Duplicate must be rejected"
            )
        assert duplicate.value.error_code == "GROUP_POLICY_DUPLICATE"
        updated = mutation_service.update_group_policy_governed(
            session, actor, policy_id, "ENGINEER", None, 1, "Role correction"
        )
        assert updated["policy"]["role_code"] == "ENGINEER"
        assert updated["policy"]["row_version"] == 2
        inactive = mutation_service.update_group_policy_governed(
            session, actor, policy_id, None, False, 2, "Policy is no longer active"
        )
        assert inactive["policy"]["status"] == "inactive"
        with pytest.raises(APIError) as stale:
            mutation_service.update_group_policy_governed(
                session, actor, policy_id, None, True, 1, "Stale request must fail"
            )
        assert stale.value.error_code == "STALE_RECORD_VERSION"
    finally:
        session.close()
        engine.dispose()


def test_kerberos_form_login_uses_persisted_group_mapping_and_never_persists_password(monkeypatch):
    _configure(monkeypatch)
    engine = _engine()
    try:
        with Session(engine) as session:
            session.add(
                db.ExternalGroupRoleMapping(
                    provider="kerberos_form",
                    external_group_identifier=ADMINISTRATOR_GROUP_IDENTIFIER,
                    role_code="ADMINISTRATOR",
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                )
            )
            session.commit()
            issued = CorporateSessionService(session, authenticator=FakeAuthenticator()).login(
                "GWP\\kgray", "not-persisted"
            )
            session.commit()
            stored = session.scalar(select(db.CorporateAuthenticationSession))
            assert issued.roles == ("ADMINISTRATOR",)
            assert stored is not None
            assert stored.token_hash != issued.token
            assert "password" not in db.CorporateAuthenticationSession.__table__.columns
            assert corporate_csrf_valid(stored, issued.csrf_token)
            assert not corporate_csrf_valid(stored, "forged")
            assert session.scalar(select(db.CorporateAuthenticationEvent.event_type)) == "LOGIN"
    finally:
        engine.dispose()


def test_unmapped_authenticated_identity_is_not_an_administrator(monkeypatch):
    _configure(monkeypatch)
    engine = _engine()
    try:
        with Session(engine) as session:
            issued = CorporateSessionService(session, authenticator=FakeAuthenticator()).login("kgray", "not-persisted")
            assert issued.roles == ("VIEWER",)
    finally:
        engine.dispose()


def test_mapping_change_removes_elevated_role_and_fresh_auth_is_scoped(monkeypatch):
    _configure(monkeypatch)
    engine = _engine()
    try:
        with Session(engine) as session:
            mapping = db.ExternalGroupRoleMapping(
                provider="kerberos_form",
                external_group_identifier=ADMINISTRATOR_GROUP_IDENTIFIER,
                role_code="ADMINISTRATOR",
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            session.add(mapping)
            session.commit()
            service = CorporateSessionService(session, authenticator=FakeAuthenticator())
            issued = service.login("kgray", "not-persisted")
            session.flush()
            row, _user = service.resolve(issued.token)
            assert row.roles_json == ["ADMINISTRATOR"]
            fresh = service.fresh_authenticate_for_step_up(
                issued.token,
                "not-persisted",
                operation_type="danger.fixture-recovery-rehearsal",
                risk_class="HIGH",
                ttl_seconds=300,
            )
            assert CorporateSessionService.fresh_step_up_valid(
                fresh, operation_type="danger.fixture-recovery-rehearsal", risk_class="HIGH"
            )
            assert not CorporateSessionService.fresh_step_up_valid(
                fresh, operation_type="different-operation", risk_class="HIGH"
            )
            mapping.is_active = False
            mapping.updated_at = datetime.now(timezone.utc)
            session.flush()
            refreshed, _user = service.resolve(issued.token)
            assert refreshed.roles_json == ["VIEWER"]
    finally:
        engine.dispose()


def test_explicit_access_precedence_and_role_change_revokes_existing_sessions(monkeypatch):
    _configure(monkeypatch)
    engine = _engine()
    try:
        with Session(engine) as session:
            now = datetime.now(timezone.utc)
            session.add(
                db.ExternalGroupRoleMapping(
                    provider="kerberos_form",
                    external_group_identifier=ADMINISTRATOR_GROUP_IDENTIFIER,
                    role_code="ADMINISTRATOR",
                    created_at=now,
                    updated_at=now,
                )
            )
            service = CorporateSessionService(session, authenticator=FakeAuthenticator())
            issued = service.login("kgray", "not-persisted")
            row, user = service.resolve(issued.token)
            registry = corporate_user_for_user(session, user.id)
            assert registry is not None
            assert registry.sign_in_count == 1
            assert (
                access_state(session, registry, groups=tuple(row.authorization_groups_json or ()))["access_source"]
                == "corporate_group"
            )
            before, after, revoked = change_explicit_access(
                session,
                registry,
                action="assign",
                role_code="ADMIN_ACCESS_MANAGER",
                reason="Focused governed access test",
                actor_user_id=user.id + 100,
                expected_row_version=registry.row_version,
            )
            assert before["effective_role"] == "ADMINISTRATOR"
            assert after["effective_role"] == "ADMIN_ACCESS_MANAGER"
            assert after["access_source"] == "explicit_user_assignment"
            assert revoked == 1
            assert row.revoked_at is not None
            preview_before, preview_after = preview_explicit_access(
                session,
                registry,
                action="remove",
                role_code=None,
            )
            assert preview_before["access_source"] == "explicit_user_assignment"
            assert preview_after["effective_role"] == "ADMINISTRATOR"
            assert preview_after["access_source"] == "corporate_group"
            _before, fallback, _revoked = change_explicit_access(
                session,
                registry,
                action="remove",
                role_code=None,
                reason="Focused fallback test",
                actor_user_id=user.id + 100,
                expected_row_version=registry.row_version,
            )
            assert fallback["effective_role"] == "ADMINISTRATOR"
            assert fallback["access_source"] == "corporate_group"
            _before, denied, _revoked = change_explicit_access(
                session,
                registry,
                action="revoke",
                role_code=None,
                reason="Focused governed denial test",
                actor_user_id=user.id + 100,
                expected_row_version=registry.row_version,
            )
            assert denied["access_source"] == "explicit_deny"
    finally:
        engine.dispose()


def test_normalization_rejects_untrusted_domain_and_empty_session(monkeypatch):
    _configure(monkeypatch)
    assert normalize_principal("kgray@gwplastics.com", "GWPLASTICS.COM") == "kgray@GWPLASTICS.COM"
    try:
        normalize_principal("OTHER\\kgray", "GWPLASTICS.COM")
    except Exception as exc:
        assert type(exc).__name__ == "CorporateAuthenticationFailure"
    else:
        raise AssertionError("untrusted domain was accepted")

    engine = _engine()
    try:
        with Session(engine) as session:
            try:
                CorporateSessionService(session, authenticator=FakeAuthenticator()).resolve("")
            except APIError as exc:
                assert exc.error_code == "CORPORATE_SESSION_REQUIRED"
            else:
                raise AssertionError("missing corporate session was accepted")
    finally:
        engine.dispose()


def test_corporate_mode_never_accepts_a_forged_identity_header(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setenv("EOAT_AUTH_PROVIDER", "kerberos_form")
    monkeypatch.setenv("EOAT_AUTH_SCOPE", "application")
    monkeypatch.setenv("EOAT_API_WRITES_ENABLED", "true")
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/eoats",
            "headers": [(b"x-eoat-identity", b"dev.admin")],
        }
    )
    for resolver in (corporate_session_actor, actor_context):
        try:
            resolver(request, None)  # type: ignore[arg-type]
        except APIError as exc:
            assert exc.error_code == "CORPORATE_SESSION_REQUIRED"
        else:
            raise AssertionError("forged header was accepted without a corporate session")


def test_http_corporate_session_enforces_admin_mapping_csrf_and_logout(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setenv("EOAT_AUTH_PROVIDER", "kerberos_form")
    monkeypatch.setenv("EOAT_AUTH_SCOPE", "application")
    monkeypatch.setenv("EOAT_API_ENVIRONMENT", "development")
    engine = _engine()
    session = Session(engine)
    try:
        now = datetime.now(timezone.utc)
        session.add(
            db.ExternalGroupRoleMapping(
                provider="kerberos_form",
                external_group_identifier=ADMINISTRATOR_GROUP_IDENTIFIER,
                role_code="ADMINISTRATOR",
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()

        def shared_session():
            yield session

        def fake_service():
            return CorporateSessionService(session, authenticator=FakeAuthenticator())

        app.dependency_overrides[get_runtime_session] = shared_session
        app.dependency_overrides[get_write_session] = shared_session
        app.dependency_overrides[corporate_session_service] = fake_service
        with TestClient(app) as client:
            assert (
                client.get("/api/v1/admin/audit/catalog", headers={"X-EOAT-Identity": "dev.admin"}).status_code == 401
            )
            login = client.post(
                "/api/v1/auth/kerberos-form/login", json={"username": "kgray", "password": "not-persisted"}
            )
            assert login.status_code == 200
            assert "password" not in login.text
            assert login.json()["permissions"] == sorted(ROLE_PERMISSIONS["ADMINISTRATOR"])
            assert login.json()["scope"] == "application"
            session_payload = client.get("/api/v1/auth/session").json()
            assert session_payload["roles"] == ["ADMINISTRATOR"]
            assert session_payload["permissions"] == login.json()["permissions"]
            assert session_payload["scope"] == "application"
            assert client.get("/api/v1/admin/audit/catalog").status_code == 200
            assert client.post("/api/v1/auth/logout").status_code == 403
            csrf = client.cookies.get("eoat_corporate_csrf")
            assert client.post("/api/v1/auth/logout", headers={"X-EOAT-CSRF-Token": csrf}).status_code == 200
            assert client.get("/api/v1/admin/audit/catalog").status_code == 401
    finally:
        app.dependency_overrides.clear()
        session.close()
        engine.dispose()


def test_provider_unavailability_fails_closed_without_a_session(monkeypatch):
    """Exercise the production route's structured provider-failure branch safely."""
    _configure(monkeypatch)
    monkeypatch.setenv("EOAT_AUTH_PROVIDER", "kerberos_form")
    monkeypatch.setenv("EOAT_AUTH_SCOPE", "application")
    engine = _engine()
    session = Session(engine)
    try:

        def shared_session():
            yield session

        def unavailable_service():
            return CorporateSessionService(session, authenticator=UnavailableAuthenticator())

        app.dependency_overrides[get_runtime_session] = shared_session
        app.dependency_overrides[get_write_session] = shared_session
        app.dependency_overrides[corporate_session_service] = unavailable_service
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/auth/kerberos-form/login",
                json={"username": "kgray", "password": "test-only-provider-failure"},
            )
            assert response.status_code == 503
            assert response.json()["error_code"] == "CORPORATE_AUTHENTICATION_UNAVAILABLE"
            assert "test-only-provider-failure" not in response.text
            assert not response.headers.get_list("set-cookie")
            assert not client.cookies
        event = session.scalar(select(db.CorporateAuthenticationEvent))
        assert event is not None
        assert (event.event_type, event.result, event.reason_code) == (
            "LOGIN",
            "DENIED",
            "KERBEROS_UNAVAILABLE",
        )
    finally:
        app.dependency_overrides.clear()
        session.close()
        engine.dispose()


def test_staging_corporate_cookies_are_secure_by_default(monkeypatch):
    monkeypatch.delenv("EOAT_API_CORPORATE_COOKIE_SECURE", raising=False)
    monkeypatch.setenv("EOAT_API_ENVIRONMENT", "staging")
    assert _cookie_secure()
