# ruff: noqa: B008
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .corporate_sessions import (
    CORPORATE_CSRF_COOKIE,
    CORPORATE_CSRF_HEADER,
    CORPORATE_SESSION_COOKIE,
    CorporateSessionService,
    corporate_csrf_valid,
)
from .database import models as db
from .database.session import get_runtime_session, get_write_session
from .errors import APIError

ROLE_PERMISSIONS = {
    "VIEWER": frozenset(),
    "TECHNICIAN": frozenset(
        {
            "installation.write",
            "audit.write",
            "maintenance.write",
            "annotation.write",
            "tag.assign",
            "fit_check.write",
            "instance.register",
        }
    ),
    "ENGINEER": frozenset(
        {
            "asset.write",
            "compatibility.write",
            "document.write",
            "annotation.write",
            "tag.manage",
            "tag.assign",
            "installation.write",
            "audit.write",
            "maintenance.write",
            "fit_check.write",
            "instance.register",
        }
    ),
    "ADMINISTRATOR": frozenset(
        {
            "*",
            "admin.area.view",
            "admin.audit.view",
            "admin.audit.export",
            "admin.data.manage",
            "admin.access.manage",
            "admin.system.diagnostics",
            "admin.diagnostics.read",
            "admin.integrity.run",
            "admin.export.audit",
            "admin.export.support",
            "admin.operations.backup",
            "admin.operations.restore",
            "admin.settings.manage",
            "admin.danger.execute",
        }
    ),
    "ADMIN_AUDITOR": frozenset({"admin.area.view", "admin.audit.view"}),
    "ADMIN_DATA_MANAGER": frozenset(
        {
            "admin.area.view",
            "admin.audit.view",
            "admin.data.view",
            "admin.eoat.edit",
            "admin.machine.edit",
            "admin.tool.edit",
            "admin.asset.archive",
            "admin.relationship.manage",
            "admin.document.manage",
            "admin.bulk.execute",
        }
    ),
    "ADMIN_SETTINGS_MANAGER": frozenset({"admin.area.view", "admin.audit.view", "admin.settings.edit"}),
    "ADMIN_ACCESS_MANAGER": frozenset(
        {"admin.area.view", "admin.audit.view", "admin.access.manage", "admin.session.manage"}
    ),
}

DEFAULT_DEVELOPMENT_IDENTITIES = {
    "dev.viewer": "VIEWER",
    "dev.technician": "TECHNICIAN",
    "dev.engineer": "ENGINEER",
    "dev.admin": "ADMINISTRATOR",
}

DEFAULT_STAGING_IDENTITIES = {
    "staging.viewer": "VIEWER",
    "staging.technician": "TECHNICIAN",
    "staging.engineer": "ENGINEER",
    "staging.admin": "ADMINISTRATOR",
}


@dataclass(frozen=True)
class ActorContext:
    user_id: int
    identity: str
    display_name: str
    role: str
    request_id: str
    application_instance_id: int | None
    client_version: str | None

    def permits(self, permission: str) -> bool:
        permissions = ROLE_PERMISSIONS.get(self.role, frozenset())
        return "*" in permissions or permission in permissions


def _configured_identities(environment: str) -> dict[str, str]:
    staging = environment == "staging_local"
    variable = "EOAT_API_STAGING_IDENTITIES" if staging else "EOAT_API_DEV_IDENTITIES"
    defaults = DEFAULT_STAGING_IDENTITIES if staging else DEFAULT_DEVELOPMENT_IDENTITIES
    raw = os.getenv(variable, "").strip()
    if not raw:
        return defaults.copy()
    try:
        values = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{variable} must be a JSON identity-to-role object") from exc
    return {str(key): str(value).upper() for key, value in values.items()}


def _local_environment() -> str:
    environment = os.getenv("EOAT_API_ENVIRONMENT", "development").strip().casefold()
    if environment not in {"development", "staging_local"}:
        raise APIError(403, "LOCAL_AUTH_FORBIDDEN", "Local rehearsal authentication is unavailable here.")
    return environment


def _corporate_auth_enabled() -> bool:
    return os.getenv("EOAT_AUTH_PROVIDER", "").strip().casefold() == "kerberos_form" and os.getenv(
        "EOAT_AUTH_SCOPE", ""
    ).strip().casefold() == "application"


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _as_utc(value: datetime) -> datetime:
    """Interpret database datetimes without an offset as UTC.

    MySQL's ``DATETIME`` has no timezone metadata, while the application
    deliberately uses timezone-aware UTC values.  The acceptance database
    therefore returns a naive value on a subsequent request.
    """
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _role_for_identity(session: Session, identity: str, environment: str) -> str | None:
    """Resolve the persisted local/test mapping and fail closed if it is unavailable."""
    mapping = session.scalar(
        select(db.DevelopmentIdentityMapping).where(
            db.DevelopmentIdentityMapping.environment == environment,
            db.DevelopmentIdentityMapping.identity == identity,
            db.DevelopmentIdentityMapping.is_active.is_(True),
        )
    )
    return mapping.role_code if mapping is not None else None


def _ensure_local_rehearsal_user(session: Session, identity: str, role_code: str, environment: str) -> db.User:
    user = session.scalar(select(db.User).where(db.User.external_identity == identity))
    if user is None:
        user = db.User(
            external_identity=identity,
            username=identity,
            display_name=identity.replace(".", " ").title(),
            authentication_provider=f"explicit_{environment}",
            last_login_at=datetime.now(timezone.utc),
            source_system=f"{environment}_auth",
        )
        session.add(user)
        session.flush()
    if not user.is_active or user.archived_at is not None:
        raise APIError(403, "IDENTITY_INACTIVE", "This identity is not permitted to write.")
    role = session.scalar(select(db.Role).where(db.Role.role_code == role_code, db.Role.is_active.is_(True)))
    if role is None:
        raise APIError(503, "AUTHORIZATION_NOT_CONFIGURED", "The configured development role is unavailable.")
    active_assignment = session.scalar(
        select(db.UserRole).where(
            db.UserRole.user_id == user.id,
            db.UserRole.role_id == role.id,
            db.UserRole.removed_at.is_(None),
        )
    )
    if active_assignment is None:
        session.add(db.UserRole(user_id=user.id, role_id=role.id, assigned_by_user_id=user.id))
    user.last_login_at = datetime.now(timezone.utc)
    return user


def actor_context(
    request: Request,
    session: Session = Depends(get_write_session),
) -> ActorContext:
    if os.getenv("EOAT_API_WRITES_ENABLED", "false").strip().casefold() not in {"1", "true", "yes", "on"}:
        raise APIError(403, "WRITES_DISABLED", "Permanent writes are disabled for this API environment.")
    if _corporate_auth_enabled():
        return corporate_session_actor(request, session)
    environment = _local_environment()
    identity = request.headers.get("X-EOAT-Identity", "").strip()
    role_code = _role_for_identity(session, identity, environment)
    if not identity or role_code not in ROLE_PERMISSIONS:
        raise APIError(401, "UNKNOWN_IDENTITY", "A configured local identity is required.")
    user = _ensure_local_rehearsal_user(session, identity, role_code, environment)
    instance_id = None
    instance_uuid = request.headers.get("X-EOAT-Application-Instance", "").strip()
    if instance_uuid:
        instance = session.scalar(
            select(db.ApplicationInstance).where(db.ApplicationInstance.instance_uuid == instance_uuid)
        )
        if instance is not None and instance.is_active:
            instance_id = instance.id
    request_id = getattr(request.state, "request_id", None) or str(uuid4())
    return ActorContext(
        user_id=user.id,
        identity=identity,
        display_name=user.display_name,
        role=role_code,
        request_id=request_id,
        application_instance_id=instance_id,
        client_version=request.headers.get("X-EOAT-Client-Version"),
    )


def read_actor_context(
    request: Request,
    session: Session = Depends(get_runtime_session),
) -> ActorContext:
    """Resolve a server-trusted local identity for read-only protected APIs.

    This deliberately has no write-gate check: administrator read contracts must
    remain independently authorized even while all mutations are disabled.
    Production identity-provider integration remains a separate Phase 5 seam.
    """
    if _corporate_auth_enabled():
        return corporate_session_actor(request, session)
    environment = _local_environment()
    identity = request.headers.get("X-EOAT-Identity", "").strip()
    role_code = _role_for_identity(session, identity, environment)
    if not identity or role_code not in ROLE_PERMISSIONS:
        raise APIError(401, "UNKNOWN_IDENTITY", "A configured local identity is required.")
    role = session.scalar(select(db.Role).where(db.Role.role_code == role_code, db.Role.is_active.is_(True)))
    if role is None:
        raise APIError(503, "AUTHORIZATION_NOT_CONFIGURED", "The configured development role is unavailable.")
    user = session.scalar(select(db.User).where(db.User.external_identity == identity))
    return ActorContext(
        user_id=user.id if user is not None else 0,
        identity=identity,
        display_name=user.display_name if user is not None else identity.replace(".", " ").title(),
        role=role_code,
        request_id=getattr(request.state, "request_id", None) or str(uuid4()),
        application_instance_id=None,
        client_version=request.headers.get("X-EOAT-Client-Version"),
    )


def corporate_session_actor(request: Request, session: Session) -> ActorContext:
    """Resolve a production actor only from the opaque corporate session."""

    row, user = CorporateSessionService(session).resolve(request.cookies.get(CORPORATE_SESSION_COOKIE, ""))
    roles = set(row.roles_json or [])
    role = next((value for value in ("ADMINISTRATOR", "ENGINEER", "TECHNICIAN", "VIEWER") if value in roles), "VIEWER")
    return ActorContext(
        user_id=user.id,
        identity=user.external_identity or user.username,
        display_name=user.display_name,
        role=role,
        request_id=getattr(request.state, "request_id", None) or str(uuid4()),
        application_instance_id=None,
        client_version=request.headers.get("X-EOAT-Client-Version"),
    )


def require(permission: str):
    def dependency(actor: ActorContext = Depends(actor_context)) -> ActorContext:
        if not actor.permits(permission):
            raise APIError(403, "PERMISSION_DENIED", "The authenticated identity does not have this permission.")
        return actor

    return dependency


def require_admin(permission: str):
    def dependency(actor: ActorContext = Depends(read_actor_context)) -> ActorContext:
        if not actor.permits(permission):
            raise APIError(403, "PERMISSION_DENIED", "The authenticated identity does not have this permission.")
        return actor

    return dependency


ADMIN_SESSION_COOKIE = "eoat_admin_rehearsal"
ADMIN_CSRF_HEADER = "X-EOAT-CSRF-Token"
ADMIN_SESSION_MAX_BODY_BYTES = 64 * 1024
DANGER_STEP_UP_TTL_SECONDS = 300


@dataclass(frozen=True)
class IssuedAdminSession:
    token: str
    csrf_token: str
    session_reference: str
    expires_at: datetime
    actor: ActorContext


def issue_admin_rehearsal_session(session: Session, identity: str, rehearsal_secret: str) -> IssuedAdminSession:
    """Create an opaque, short-lived local/test session; unavailable outside local environments."""
    environment = _local_environment()
    configured_secret = os.getenv("EOAT_API_ADMIN_REHEARSAL_SECRET", "")
    if not configured_secret or not hmac.compare_digest(configured_secret, rehearsal_secret):
        raise APIError(401, "ADMIN_REHEARSAL_AUTHENTICATION_FAILED", "The development/test Administrator sign-in could not be verified.")
    if not identity or len(identity) > 255:
        raise APIError(422, "INVALID_REHEARSAL_IDENTITY", "A configured development/test identity is required.")
    role_code = _role_for_identity(session, identity, environment)
    if role_code not in ROLE_PERMISSIONS:
        raise APIError(401, "UNKNOWN_IDENTITY", "A configured local identity is required.")
    user = _ensure_local_rehearsal_user(session, identity, role_code, environment)
    token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=30)
    record = db.AdminRehearsalSession(
        session_reference=str(uuid4()),
        session_token_hash=_sha256(token),
        csrf_token_hash=_sha256(csrf_token),
        user_id=user.id,
        environment=environment,
        expires_at=expires_at,
        last_seen_at=now,
    )
    session.add(record)
    session.flush()
    actor = ActorContext(
        user_id=user.id,
        identity=identity,
        display_name=user.display_name,
        role=role_code,
        request_id="",  # Bound to the actual request by the route dependency.
        application_instance_id=None,
        client_version=None,
    )
    return IssuedAdminSession(token, csrf_token, record.session_reference, expires_at, actor)


def admin_session_actor(
    request: Request,
    session: Session = Depends(get_write_session),
) -> ActorContext:
    """Resolve a Phase 3 mutation actor only from the opaque server-side session."""
    if _corporate_auth_enabled():
        return corporate_session_actor(request, session)
    environment = _local_environment()
    token = request.cookies.get(ADMIN_SESSION_COOKIE, "")
    if not token:
        raise APIError(401, "ADMIN_SESSION_REQUIRED", "A development/test Administrator session is required.")
    record = session.scalar(
        select(db.AdminRehearsalSession).where(db.AdminRehearsalSession.session_token_hash == _sha256(token))
    )
    now = datetime.now(timezone.utc)
    if record is None or record.environment != environment or record.revoked_at is not None or _as_utc(record.expires_at) <= now:
        raise APIError(401, "ADMIN_SESSION_EXPIRED", "The Administrator session is expired or unavailable.")
    role = session.scalar(
        select(db.Role)
        .join(db.UserRole, db.UserRole.role_id == db.Role.id)
        .where(db.UserRole.user_id == record.user_id, db.UserRole.removed_at.is_(None), db.Role.is_active.is_(True))
        .order_by(db.UserRole.assigned_at.desc())
    )
    user = session.get(db.User, record.user_id)
    if user is None or not user.is_active or user.archived_at is not None or role is None:
        raise APIError(403, "ADMIN_SESSION_REVOKED", "The Administrator session is no longer authorized.")
    record.last_seen_at = now
    return ActorContext(
        user_id=user.id,
        identity=user.external_identity or user.username,
        display_name=user.display_name,
        role=role.role_code,
        request_id=getattr(request.state, "request_id", None) or str(uuid4()),
        application_instance_id=None,
        client_version=request.headers.get("X-EOAT-Client-Version"),
    )


def require_admin_session(permission: str):
    def dependency(actor: ActorContext = Depends(admin_session_actor)) -> ActorContext:
        if not actor.permits(permission):
            raise APIError(403, "PERMISSION_DENIED", "The authenticated identity does not have this capability.")
        return actor

    return dependency


def require_admin_mutation(permission: str):
    def dependency(
        request: Request,
        actor: ActorContext = Depends(admin_session_actor),
        session: Session = Depends(get_write_session),
    ) -> ActorContext:
        content_type = request.headers.get("content-type", "").split(";", 1)[0].casefold()
        if content_type != "application/json":
            raise APIError(415, "CONTENT_TYPE_REQUIRED", "Administrator mutations require application/json.")
        content_length = request.headers.get("content-length")
        if content_length and (not content_length.isdigit() or int(content_length) > ADMIN_SESSION_MAX_BODY_BYTES):
            raise APIError(413, "REQUEST_TOO_LARGE", "The Administrator mutation request is too large.")
        if _corporate_auth_enabled():
            record, _user = CorporateSessionService(session).resolve(request.cookies.get(CORPORATE_SESSION_COOKIE, ""))
            submitted = request.headers.get(CORPORATE_CSRF_HEADER, "")
            if request.cookies.get(CORPORATE_CSRF_COOKIE, "") != submitted or not corporate_csrf_valid(record, submitted):
                raise APIError(403, "CSRF_INVALID", "The Administrator mutation could not be verified.")
        else:
            token = request.cookies.get(ADMIN_SESSION_COOKIE, "")
            record = session.scalar(
                select(db.AdminRehearsalSession).where(db.AdminRehearsalSession.session_token_hash == _sha256(token))
            )
            submitted = request.headers.get(ADMIN_CSRF_HEADER, "")
            if record is None or not submitted or not hmac.compare_digest(record.csrf_token_hash, _sha256(submitted)):
                raise APIError(403, "CSRF_INVALID", "The Administrator mutation could not be verified.")
        if not actor.permits(permission):
            raise APIError(403, "PERMISSION_DENIED", "The authenticated identity does not have this capability.")
        return actor

    return dependency


def issue_danger_step_up(
    request: Request,
    session: Session,
    actor: ActorContext,
    *,
    operation_type: str,
    risk_class: str,
    rehearsal_step_up_secret: str,
) -> db.AdminDangerStepUp:
    """Issue a development/test-only step-up proof bound to this session.

    The proof is an additional recent server-side verification of the existing
    rehearsal secret. It deliberately is not described as a user password or
    production corporate reauthentication.
    """
    _local_environment()
    configured_secret = os.getenv("EOAT_API_ADMIN_REHEARSAL_SECRET", "")
    if not configured_secret or not hmac.compare_digest(configured_secret, rehearsal_step_up_secret):
        raise APIError(401, "DANGER_STEP_UP_REJECTED", "The development/test step-up proof could not be verified.")
    if not actor.permits("admin.danger.execute"):
        raise APIError(403, "PERMISSION_DENIED", "The authenticated identity does not have this capability.")
    token = request.cookies.get(ADMIN_SESSION_COOKIE, "")
    rehearsal = session.scalar(
        select(db.AdminRehearsalSession).where(db.AdminRehearsalSession.session_token_hash == _sha256(token))
    )
    now = datetime.now(timezone.utc)
    if rehearsal is None or rehearsal.revoked_at is not None or _as_utc(rehearsal.expires_at) <= now:
        raise APIError(401, "ADMIN_SESSION_EXPIRED", "The Administrator session is expired or unavailable.")
    proof = db.AdminDangerStepUp(
        step_up_reference=str(uuid4()),
        admin_rehearsal_session_id=rehearsal.id,
        operation_type=operation_type,
        risk_class=risk_class,
        expires_at=now + timedelta(seconds=DANGER_STEP_UP_TTL_SECONDS),
    )
    session.add(proof)
    session.flush()
    return proof


def require_active_danger_step_up(
    request: Request,
    session: Session,
    actor: ActorContext,
    *,
    operation_type: str,
    risk_class: str,
) -> db.AdminDangerStepUp:
    """Return the currently valid scoped proof or fail closed."""
    _local_environment()
    if not actor.permits("admin.danger.execute"):
        raise APIError(403, "PERMISSION_DENIED", "The authenticated identity does not have this capability.")
    token = request.cookies.get(ADMIN_SESSION_COOKIE, "")
    rehearsal = session.scalar(
        select(db.AdminRehearsalSession).where(db.AdminRehearsalSession.session_token_hash == _sha256(token))
    )
    now = datetime.now(timezone.utc)
    if rehearsal is None or rehearsal.revoked_at is not None or _as_utc(rehearsal.expires_at) <= now:
        raise APIError(401, "ADMIN_SESSION_EXPIRED", "The Administrator session is expired or unavailable.")
    proof = session.scalar(
        select(db.AdminDangerStepUp)
        .where(
            db.AdminDangerStepUp.admin_rehearsal_session_id == rehearsal.id,
            db.AdminDangerStepUp.operation_type == operation_type,
            db.AdminDangerStepUp.risk_class == risk_class,
        )
        .order_by(db.AdminDangerStepUp.issued_at.desc())
    )
    # A new step-up supersedes the prior proof for this scoped operation.  Do
    # not silently fall back to an earlier proof when the newest was revoked
    # or expired: that would defeat explicit revocation during a live session.
    if proof is None or proof.revoked_at is not None or _as_utc(proof.expires_at) <= now:
        raise APIError(403, "DANGER_STEP_UP_REQUIRED", "A current development/test step-up proof is required.")
    return proof
