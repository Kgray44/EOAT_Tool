"""Corporate-user registry and server-authoritative access resolution.

Only successfully authenticated identities enter this registry.  The resolver
is deliberately shared by login, session validation, and Admin access
management so the browser can never choose an effective role.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .database import models as db
from .errors import APIError

DEFAULT_ROLE = "VIEWER"
ROLE_PRIORITY = (
    "ADMINISTRATOR",
    "ADMIN_ACCESS_MANAGER",
    "ADMIN_SETTINGS_MANAGER",
    "ADMIN_DATA_MANAGER",
    "ADMIN_AUDITOR",
    "ENGINEER",
    "TECHNICIAN",
    "VIEWER",
)
ACCESS_SOURCES = frozenset({"explicit_user_assignment", "corporate_group", "default", "explicit_deny"})


@dataclass(frozen=True)
class EffectiveAccess:
    role_code: str
    source: str
    group_roles: tuple[str, ...] = ()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def register_successful_login(session: Session, user: db.User, *, provider: str, canonical_identity: str, display_name: str) -> db.CorporateUser:
    """Create or refresh the one EOAT-owned registry record for this login."""

    now = _now()
    row = session.scalar(select(db.CorporateUser).where(db.CorporateUser.user_id == user.id))
    if row is None:
        row = db.CorporateUser(
            user_uuid=str(uuid4()),
            user_id=user.id,
            provider=provider,
            canonical_identity=canonical_identity.casefold(),
            display_name=display_name,
            first_successful_sign_in_at=now,
            last_successful_sign_in_at=now,
            sign_in_count=1,
            source_system="corporate_auth",
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        session.flush()
        return row
    row.provider = provider
    row.canonical_identity = canonical_identity.casefold()
    row.display_name = display_name
    row.last_successful_sign_in_at = now
    row.sign_in_count += 1
    row.row_version += 1
    return row


def _group_roles(session: Session, *, provider: str, groups: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    if not groups:
        return ()
    rows = session.scalars(
        select(db.ExternalGroupRoleMapping).where(
            db.ExternalGroupRoleMapping.provider == provider,
            db.ExternalGroupRoleMapping.external_group_identifier.in_(tuple(groups)),
            db.ExternalGroupRoleMapping.is_active.is_(True),
            db.ExternalGroupRoleMapping.explicit_deny.is_(False),
        )
    ).all()
    return tuple(sorted({row.role_code for row in rows if row.role_code in ROLE_PRIORITY}))


def resolve_effective_access(session: Session, corporate_user: db.CorporateUser, *, groups: tuple[str, ...] | list[str] = ()) -> EffectiveAccess:
    """Resolve access in the only permitted precedence order."""

    if not corporate_user.is_active or corporate_user.archived_at is not None or corporate_user.explicit_denied:
        return EffectiveAccess(DEFAULT_ROLE, "explicit_deny")
    if corporate_user.explicit_role_code:
        return EffectiveAccess(corporate_user.explicit_role_code, "explicit_user_assignment")
    group_roles = _group_roles(session, provider=corporate_user.provider, groups=groups)
    if group_roles:
        return EffectiveAccess(next(role for role in ROLE_PRIORITY if role in group_roles), "corporate_group", group_roles)
    return EffectiveAccess(DEFAULT_ROLE, "default")


def corporate_user_for_user(session: Session, user_id: int) -> db.CorporateUser | None:
    return session.scalar(select(db.CorporateUser).where(db.CorporateUser.user_id == user_id))


def access_state(session: Session, corporate_user: db.CorporateUser, *, groups: tuple[str, ...] | list[str] = ()) -> dict[str, object]:
    effective = resolve_effective_access(session, corporate_user, groups=groups)
    return {
        "effective_role": effective.role_code,
        "access_source": effective.source,
        "group_roles": list(effective.group_roles),
        "explicit_role": corporate_user.explicit_role_code,
        "explicit_denied": corporate_user.explicit_denied,
    }


def active_corporate_session_count(session: Session, user_id: int) -> int:
    now = _now()
    return session.scalar(
        select(func.count(db.CorporateAuthenticationSession.id)).where(
            db.CorporateAuthenticationSession.user_id == user_id,
            db.CorporateAuthenticationSession.revoked_at.is_(None),
            db.CorporateAuthenticationSession.expires_at > now,
        )
    ) or 0


def latest_authorization_groups(session: Session, user_id: int) -> tuple[str, ...]:
    """Return only the bounded, role-relevant groups from the latest session."""

    row = session.scalar(
        select(db.CorporateAuthenticationSession)
        .where(db.CorporateAuthenticationSession.user_id == user_id)
        .order_by(db.CorporateAuthenticationSession.authenticated_at.desc(), db.CorporateAuthenticationSession.id.desc())
    )
    return tuple(row.authorization_groups_json or ()) if row is not None else ()


def revoke_active_sessions(session: Session, user_id: int, *, reason: str) -> int:
    now = _now()
    rows = session.scalars(
        select(db.CorporateAuthenticationSession).where(
            db.CorporateAuthenticationSession.user_id == user_id,
            db.CorporateAuthenticationSession.revoked_at.is_(None),
            db.CorporateAuthenticationSession.expires_at > now,
        )
    ).all()
    for row in rows:
        row.revoked_at = now
        row.revoke_reason = reason
    return len(rows)


def ensure_recovery_path(session: Session, target: db.CorporateUser, *, action: str) -> None:
    """Fail closed before removing the last EOAT-controlled Admin recovery path."""

    if action not in {"revoke", "remove"} or target.explicit_role_code != "ADMINISTRATOR":
        return
    mapping_exists = session.scalar(
        select(db.ExternalGroupRoleMapping.id).where(
            db.ExternalGroupRoleMapping.role_code == "ADMINISTRATOR",
            db.ExternalGroupRoleMapping.is_active.is_(True),
            db.ExternalGroupRoleMapping.explicit_deny.is_(False),
        )
    )
    other_admin = session.scalar(
        select(func.count(db.CorporateUser.id)).where(
            db.CorporateUser.id != target.id,
            db.CorporateUser.is_active.is_(True),
            db.CorporateUser.explicit_denied.is_(False),
            db.CorporateUser.explicit_role_code == "ADMINISTRATOR",
        )
    ) or 0
    if not mapping_exists and not other_admin:
        raise APIError(409, "ADMIN_RECOVERY_PATH_REQUIRED", "This change would remove the final viable administrative recovery path.")


def preview_explicit_access(session: Session, corporate_user: db.CorporateUser, *, action: str, role_code: str | None) -> tuple[dict[str, object], dict[str, object]]:
    """Return the governed before/after view without changing database state."""

    if action == "assign" and role_code not in ROLE_PRIORITY:
        raise APIError(422, "ROLE_INVALID", "The requested application role is not supported.")
    if action != "assign" and role_code is not None:
        raise APIError(422, "ROLE_NOT_APPLICABLE", "Only an assignment may include a role.")
    if action not in {"assign", "revoke", "restore", "remove"}:
        raise APIError(422, "ACCESS_ACTION_INVALID", "The requested access action is not supported.")
    groups = latest_authorization_groups(session, corporate_user.user_id)
    before = access_state(session, corporate_user, groups=groups)
    explicit_role = role_code if action == "assign" else (corporate_user.explicit_role_code if action == "restore" else None)
    explicit_denied = action == "revoke"
    # A preview cannot infer unpersisted group membership for a historical
    # row, so its fallback state is explicitly represented as such.
    if explicit_denied:
        after = {**before, "effective_role": DEFAULT_ROLE, "access_source": "explicit_deny", "explicit_role": explicit_role, "explicit_denied": True}
    elif explicit_role:
        after = {**before, "effective_role": explicit_role, "access_source": "explicit_user_assignment", "explicit_role": explicit_role, "explicit_denied": False}
    else:
        after = {**before, "effective_role": DEFAULT_ROLE, "access_source": "default", "explicit_role": None, "explicit_denied": False}
    return before, after


def change_explicit_access(session: Session, corporate_user: db.CorporateUser, *, action: str, role_code: str | None, reason: str, actor_user_id: int, expected_row_version: int) -> tuple[dict[str, object], dict[str, object], int]:
    if corporate_user.row_version != expected_row_version:
        raise APIError(409, "ROW_VERSION_CONFLICT", "The user access record changed; refresh and review the current state.")
    if action == "assign" and role_code not in ROLE_PRIORITY:
        raise APIError(422, "ROLE_INVALID", "The requested application role is not supported.")
    if action != "assign" and role_code is not None:
        raise APIError(422, "ROLE_NOT_APPLICABLE", "Only an assignment may include a role.")
    ensure_recovery_path(session, corporate_user, action=action)
    groups = latest_authorization_groups(session, corporate_user.user_id)
    before = access_state(session, corporate_user, groups=groups)
    if action == "assign":
        corporate_user.explicit_role_code = role_code
        corporate_user.explicit_denied = False
    elif action == "revoke":
        corporate_user.explicit_role_code = None
        corporate_user.explicit_denied = True
    elif action == "restore":
        corporate_user.explicit_denied = False
    elif action == "remove":
        corporate_user.explicit_role_code = None
        corporate_user.explicit_denied = False
    else:
        raise APIError(422, "ACCESS_ACTION_INVALID", "The requested access action is not supported.")
    corporate_user.access_reason = reason
    corporate_user.access_changed_at = _now()
    corporate_user.access_changed_by_user_id = actor_user_id
    corporate_user.updated_by_user_id = actor_user_id
    corporate_user.row_version += 1
    after = access_state(session, corporate_user, groups=groups)
    revoked = revoke_active_sessions(session, corporate_user.user_id, reason=f"access_{action}")
    return before, after, revoked
