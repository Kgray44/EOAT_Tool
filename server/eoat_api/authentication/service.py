from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import models as db
from ..errors import APIError
from .audit import record_auth_event
from .configuration import AuthenticationConfiguration
from .exceptions import AuthenticationUnavailableError
from .identity_models import AuthenticatedIdentity
from .permissions import effective_permissions
from .providers import DevelopmentAuthenticationProvider, LDAPAuthenticationProvider, SAMLAuthenticationProvider
from .role_mapping import resolve_roles


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


class AuthenticationService:
    def __init__(self, session: Session, configuration: AuthenticationConfiguration | None = None):
        self.session = session
        self.configuration = configuration or AuthenticationConfiguration.from_environment()
        self.provider = self._provider()

    def _provider(self):
        provider = self.configuration.provider
        if provider == "development":
            return DevelopmentAuthenticationProvider(self.configuration.environment)
        if provider == "saml":
            return SAMLAuthenticationProvider()
        if provider == "ldap":
            return LDAPAuthenticationProvider()
        return None

    def public_configuration(self) -> dict:
        health = self.provider.health_check() if self.provider else None
        return {
            "provider": self.configuration.provider,
            "environment": self.configuration.environment,
            "scope": "settings_only",
            "startup_authentication_required": False,
            "ordinary_application_access_requires_login": False,
            "settings_authentication_available": bool(health and health.available),
            "production_approved": bool(health and health.production_approved),
            "provider_configured": bool(health and health.configured),
            "missing_configuration": list(health.missing_configuration) if health else ["provider_selection"],
            "message": health.message if health else "Authentication provider selection is awaiting IT",
            "development_identities": ["dev.viewer", "dev.technician", "dev.engineer", "dev.admin"]
            if self.configuration.provider == "development"
            else [],
        }

    def begin_login(self, context: dict) -> dict:
        if self.provider is None:
            raise APIError(503, "AUTH_PROVIDER_UNAVAILABLE", "Administrator authentication is not configured.")
        try:
            return self.provider.begin_login(context)
        except AuthenticationUnavailableError as exc:
            raise APIError(
                503,
                "AUTH_PROVIDER_UNAVAILABLE",
                "Administrator authentication is currently unavailable. EOAT Atlas remains fully usable, but Settings editing cannot be unlocked.",
                details={"provider_message": str(exc)},
                retryable=True,
            ) from exc

    def complete_development_login(
        self,
        identity_key: str,
        *,
        application_instance_id: int | None = None,
        request_id: str | None = None,
        client_version: str | None = None,
        source_ip: str | None = None,
    ) -> dict:
        if self.configuration.provider != "development":
            raise APIError(404, "DEVELOPMENT_AUTH_DISABLED", "Development authentication is not active.")
        try:
            challenge = self.begin_login({"identity": identity_key})
            identity = self.provider.complete_login(challenge)
        except (AuthenticationUnavailableError, KeyError) as exc:
            record_auth_event(
                self.session,
                "SETTINGS_ADMIN_LOGIN_FAILED",
                result="DENIED",
                provider="development",
                request_id=request_id,
                reason_code="INVALID_DEVELOPMENT_IDENTITY",
                source_ip=source_ip,
            )
            raise APIError(401, "AUTHENTICATION_FAILED", "Administrator authentication failed.") from exc
        user = self._provision_user(identity)
        roles = resolve_roles(self.session, identity.provider, identity.group_identifiers)
        self._sync_user_roles(user, roles)
        permissions = effective_permissions(roles)
        token, auth_session = self._issue_session(
            user,
            identity,
            roles,
            permissions,
            application_instance_id=application_instance_id,
        )
        record_auth_event(
            self.session,
            "SETTINGS_ADMIN_LOGIN_SUCCEEDED",
            result="SUCCEEDED",
            external_subject=identity.external_subject,
            user_id=user.id,
            application_instance_id=application_instance_id,
            provider=identity.provider,
            request_id=request_id,
            operation="settings.edit",
            client_version=client_version,
            source_ip=source_ip,
        )
        if "settings.edit" in permissions:
            record_auth_event(
                self.session,
                "SETTINGS_ADMIN_MODE_ENTERED",
                result="SUCCEEDED",
                external_subject=identity.external_subject,
                user_id=user.id,
                provider=identity.provider,
                request_id=request_id,
            )
        return {"access_token": token, "token_type": "bearer", **self.session_payload(auth_session, user)}

    def _provision_user(self, identity: AuthenticatedIdentity) -> db.User:
        user = self.session.scalar(select(db.User).where(db.User.external_subject == identity.external_subject))
        if user is None:
            user = self.session.scalar(select(db.User).where(db.User.external_identity == identity.external_subject))
        if user is None:
            if not self.configuration.jit_provisioning:
                raise APIError(403, "USER_NOT_PROVISIONED", "This identity is not provisioned for Settings access.")
            user = db.User(
                external_identity=identity.external_subject,
                external_subject=identity.external_subject,
                username=identity.username,
                display_name=identity.display_name,
                email=identity.email,
                authentication_provider=identity.provider,
                first_login_at=identity.authentication_time,
                source_system="enterprise_authentication",
            )
            self.session.add(user)
            self.session.flush()
        if not user.is_active or user.archived_at is not None:
            raise APIError(403, "USER_DISABLED", "This identity is not active.")
        user.external_subject = identity.external_subject
        user.display_name = identity.display_name
        user.email = identity.email
        user.authentication_provider = identity.provider
        user.last_login_at = identity.authentication_time
        user.first_login_at = user.first_login_at or identity.authentication_time
        user.last_role_sync_at = identity.authentication_time
        return user

    def _sync_user_roles(self, user: db.User, roles: tuple[str, ...]) -> None:
        now = datetime.now(timezone.utc)
        active = self.session.scalars(
            select(db.UserRole).where(db.UserRole.user_id == user.id, db.UserRole.removed_at.is_(None))
        ).all()
        role_rows = self.session.scalars(select(db.Role).where(db.Role.role_code.in_(roles))).all() if roles else []
        requested_ids = {row.id for row in role_rows if row.is_active}
        active_ids = {row.role_id for row in active}
        for assignment in active:
            if assignment.role_id not in requested_ids:
                assignment.removed_at = now
        for role in role_rows:
            if role.is_active and role.id not in active_ids:
                self.session.add(db.UserRole(user_id=user.id, role_id=role.id, assigned_by_user_id=user.id))
        user.last_role_sync_at = now

    def _issue_session(
        self,
        user: db.User,
        identity: AuthenticatedIdentity,
        roles: tuple[str, ...],
        permissions: frozenset[str],
        *,
        application_instance_id: int | None,
    ) -> tuple[str, db.AuthenticationSession]:
        token = secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc)
        row = db.AuthenticationSession(
            session_uuid=str(uuid4()),
            token_hash=hashlib.sha256(token.encode()).hexdigest(),
            user_id=user.id,
            application_instance_id=application_instance_id,
            provider=identity.provider,
            authentication_method=identity.authentication_method,
            roles_json=list(roles),
            permissions_json=sorted(permissions),
            authenticated_at=identity.authentication_time,
            expires_at=now + timedelta(minutes=self.configuration.session_minutes),
        )
        self.session.add(row)
        self.session.flush()
        return token, row

    def resolve_session(self, token: str) -> tuple[db.AuthenticationSession, db.User]:
        if not token:
            raise APIError(401, "AUTHENTICATION_REQUIRED", "Administrator authentication is required.")
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        row = self.session.scalar(select(db.AuthenticationSession).where(db.AuthenticationSession.token_hash == token_hash))
        if row is None or row.revoked_at is not None:
            raise APIError(401, "SESSION_INVALID", "The Settings administrator session is invalid or revoked.")
        if _utc(row.expires_at) <= datetime.now(timezone.utc):
            row.revoked_at = datetime.now(timezone.utc)
            row.revocation_reason = "expired"
            record_auth_event(self.session, "SETTINGS_ADMIN_SESSION_EXPIRED", result="EXPIRED", user_id=row.user_id)
            raise APIError(401, "SESSION_EXPIRED", "The Settings administrator session has expired.")
        user = self.session.get(db.User, row.user_id)
        if user is None or not user.is_active or user.archived_at is not None:
            raise APIError(403, "USER_DISABLED", "Administrator access has been revoked.")
        return row, user

    def require_permission(self, token: str, permission: str) -> dict:
        row, user = self.resolve_session(token)
        if row.provider != self.configuration.provider:
            row.revoked_at = datetime.now(timezone.utc)
            row.revocation_reason = "provider_changed"
            raise APIError(401, "SESSION_PROVIDER_CHANGED", "The authentication provider changed; sign in again.")
        health = self.provider.health_check() if self.provider else None
        if not health or not health.available:
            row.revoked_at = datetime.now(timezone.utc)
            row.revocation_reason = "provider_unavailable"
            raise APIError(
                503,
                "AUTH_PROVIDER_UNAVAILABLE",
                "Administrator authentication is unavailable. Settings have been relocked; normal application use is unaffected.",
                retryable=True,
            )
        role_codes = tuple(
            self.session.scalars(
                select(db.Role.role_code)
                .join(db.UserRole, db.UserRole.role_id == db.Role.id)
                .where(
                    db.UserRole.user_id == user.id,
                    db.UserRole.removed_at.is_(None),
                    db.Role.is_active.is_(True),
                )
            ).all()
        )
        live_permissions = effective_permissions(role_codes)
        row.roles_json = list(role_codes)
        row.permissions_json = sorted(live_permissions)
        if permission not in live_permissions:
            row.revoked_at = datetime.now(timezone.utc)
            row.revocation_reason = "permission_lost"
            record_auth_event(
                self.session,
                "SETTINGS_ADMIN_ACCESS_DENIED",
                result="DENIED",
                user_id=user.id,
                provider=row.provider,
                operation=permission,
                reason_code="PERMISSION_MISSING",
            )
            raise APIError(403, "PERMISSION_DENIED", "The authenticated identity does not have this permission.")
        return self.session_payload(row, user)

    def public_settings(self) -> list[dict]:
        rows = self.session.scalars(
            select(db.SystemSetting).where(
                db.SystemSetting.is_active.is_(True),
                db.SystemSetting.archived_at.is_(None),
                db.SystemSetting.is_sensitive.is_(False),
            ).order_by(db.SystemSetting.setting_key)
        ).all()
        return [self._setting_payload(row) for row in rows]

    def write_public_setting(self, token: str, setting_key: str, value, description: str | None = None) -> dict:
        authorization = self.require_permission(token, "settings.edit")
        row = self.session.scalar(select(db.SystemSetting).where(db.SystemSetting.setting_key == setting_key))
        if row is not None and row.is_sensitive:
            raise APIError(403, "SENSITIVE_SETTING_BLOCKED", "Sensitive settings cannot be changed through this endpoint.")
        if row is None:
            row = db.SystemSetting(
                setting_key=setting_key,
                setting_value_json=value,
                value_type=self._value_type(value),
                description=description,
                is_sensitive=False,
                created_by_user_id=self.session.scalar(
                    select(db.User.id).where(db.User.external_subject == authorization["identity"]["external_subject"])
                ),
            )
            self.session.add(row)
        else:
            row.setting_value_json = value
            row.value_type = self._value_type(value)
            row.description = description if description is not None else row.description
            row.row_version += 1
            row.updated_by_user_id = self.session.scalar(
                select(db.User.id).where(db.User.external_subject == authorization["identity"]["external_subject"])
            )
        self.session.flush()
        self.audit_settings_action(token, "SETTINGS_UPDATED", f"settings.write:{setting_key}")
        return self._setting_payload(row)

    @staticmethod
    def _value_type(value) -> str:
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "boolean"
        if isinstance(value, int):
            return "integer"
        if isinstance(value, float):
            return "number"
        if isinstance(value, str):
            return "string"
        if isinstance(value, list):
            return "array"
        return "object"

    @staticmethod
    def _setting_payload(row: db.SystemSetting) -> dict:
        return {
            "key": row.setting_key,
            "value": row.setting_value_json,
            "value_type": row.value_type,
            "description": row.description,
            "row_version": row.row_version,
        }

    def logout(self, token: str) -> None:
        row, user = self.resolve_session(token)
        row.revoked_at = datetime.now(timezone.utc)
        row.revocation_reason = "logout"
        record_auth_event(
            self.session,
            "SETTINGS_ADMIN_MODE_EXITED",
            result="SUCCEEDED",
            user_id=user.id,
            provider=row.provider,
        )

    def audit_settings_action(self, token: str, event_type: str, operation: str) -> dict:
        allowed = {"SETTINGS_UPDATED", "SETTINGS_DEFAULT_CHANGED", "AUTH_CONFIGURATION_CHANGED"}
        if event_type not in allowed:
            raise APIError(422, "INVALID_AUTH_AUDIT_EVENT", "Unsupported Settings audit event.")
        row, user = self.resolve_session(token)
        if "settings.edit" not in set(row.permissions_json or []):
            raise APIError(403, "PERMISSION_DENIED", "The authenticated identity cannot edit Settings.")
        record_auth_event(
            self.session,
            event_type,
            result="SUCCEEDED",
            external_subject=user.external_subject or user.external_identity,
            user_id=user.id,
            application_instance_id=row.application_instance_id,
            provider=row.provider,
            operation=operation,
        )
        return {"recorded": True, "event_type": event_type}

    @staticmethod
    def session_payload(row: db.AuthenticationSession, user: db.User) -> dict:
        return {
            "authenticated": True,
            "session_id": row.session_uuid,
            "provider": row.provider,
            "identity": {
                "external_subject": user.external_subject or user.external_identity,
                "username": user.username,
                "display_name": user.display_name,
                "email": user.email,
            },
            "roles": list(row.roles_json or []),
            "permissions": list(row.permissions_json or []),
            "authenticated_at": row.authenticated_at,
            "expires_at": row.expires_at,
            "scope": "settings_only",
        }
