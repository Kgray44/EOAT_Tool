# ruff: noqa: B008
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import models as db
from .database.session import get_write_session
from .errors import APIError

ROLE_PERMISSIONS = {
    # The application principal preserves the product's normal no-login
    # experience.  It can perform ordinary EOAT Atlas work, but never a
    # Settings administration operation.
    "APPLICATION_USER": frozenset({"*"}),
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
            "installation.override_compatibility",
            "audit.write",
            "maintenance.write",
            "fit_check.write",
            "instance.register",
        }
    ),
    "ADMINISTRATOR": frozenset({"*"}),
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
        if self.role == "APPLICATION_USER":
            return not permission.startswith("settings.") and permission != "installation.override_compatibility"
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


def _ensure_local_rehearsal_user(session: Session, identity: str, role_code: str, environment: str) -> db.User:
    user = session.scalar(select(db.User).where(db.User.external_identity == identity))
    if user is None:
        user = db.User(
            external_identity=identity,
            external_subject=identity,
            username=identity,
            display_name=identity.replace(".", " ").title(),
            authentication_provider=f"explicit_{environment}",
            last_login_at=datetime.now(timezone.utc),
            source_system=f"{environment}_auth",
        )
        session.add(user)
        session.flush()
    elif not user.external_subject:
        user.external_subject = identity
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
    identity = request.headers.get("X-EOAT-Identity", "").strip()
    if not identity:
        user = _ensure_application_user(session)
        request_id = getattr(request.state, "request_id", None) or str(uuid4())
        return ActorContext(
            user_id=user.id,
            identity="application.unauthenticated",
            display_name="EOAT Atlas Application",
            role="APPLICATION_USER",
            request_id=request_id,
            application_instance_id=_application_instance_id(request, session),
            client_version=request.headers.get("X-EOAT-Client-Version"),
        )
    environment = os.getenv("EOAT_API_ENVIRONMENT", "development").strip().casefold()
    if environment not in {"development", "staging_local"}:
        raise APIError(403, "LOCAL_AUTH_FORBIDDEN", "Local rehearsal authentication is unavailable here.")
    configured = _configured_identities(environment)
    role_code = configured.get(identity)
    if not identity or role_code not in ROLE_PERMISSIONS:
        raise APIError(401, "UNKNOWN_IDENTITY", "A configured local identity is required.")
    user = _ensure_local_rehearsal_user(session, identity, role_code, environment)
    instance_id = _application_instance_id(request, session)
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


def _ensure_application_user(session: Session) -> db.User:
    identity = "application.unauthenticated"
    user = session.scalar(select(db.User).where(db.User.external_identity == identity))
    if user is None:
        user = db.User(
            external_identity=identity,
            external_subject=identity,
            username=identity,
            display_name="EOAT Atlas Application",
            authentication_provider="application_instance",
            source_system="application_runtime",
        )
        session.add(user)
        session.flush()
    elif not user.external_subject:
        user.external_subject = identity
    if not user.is_active or user.archived_at is not None:
        raise APIError(503, "APPLICATION_IDENTITY_DISABLED", "The application identity is unavailable.")
    return user


def _application_instance_id(request: Request, session: Session) -> int | None:
    instance_uuid = request.headers.get("X-EOAT-Application-Instance", "").strip()
    if not instance_uuid:
        return None
    instance = session.scalar(
        select(db.ApplicationInstance).where(db.ApplicationInstance.instance_uuid == instance_uuid)
    )
    return instance.id if instance is not None and instance.is_active else None


def require(permission: str):
    def dependency(actor: ActorContext = Depends(actor_context)) -> ActorContext:
        if not actor.permits(permission):
            raise APIError(403, "PERMISSION_DENIED", "The authenticated identity does not have this permission.")
        return actor

    return dependency
