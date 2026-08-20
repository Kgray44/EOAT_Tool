"""Governed Corporate Users & Access Administrator APIs."""

# ruff: noqa: B008

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..corporate_users import (
    access_state,
    active_corporate_session_count,
    change_explicit_access,
    latest_authorization_groups,
    preview_explicit_access,
)
from ..database import models as db
from ..database.session import get_runtime_session, get_write_session
from ..errors import APIError, not_found
from ..security import ActorContext, require_admin_mutation, require_admin_session
from ..write_services import idempotent
from .service import AuditEventWriter
from .taxonomy import AuditAction, AuditSource

router = APIRouter(prefix="/api/v1/admin/users", tags=["admin-corporate-users"])
AccessAction = Literal["assign", "revoke", "restore", "remove"]


class CorporateAccessRequest(BaseModel):
    action: AccessAction
    role_code: str | None = Field(default=None, max_length=64)
    reason: str = Field(min_length=3, max_length=2000)
    expected_row_version: int = Field(ge=1)
    confirmation: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def role_matches_action(self):
        if self.action == "assign" and not self.role_code:
            raise ValueError("A role is required for an assignment.")
        if self.action != "assign" and self.role_code is not None:
            raise ValueError("Only an assignment may include a role.")
        return self


class CorporateSessionRevokeRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=512)
    confirmation: str = Field(min_length=3, max_length=255)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _session_state(row: db.CorporateAuthenticationSession) -> str:
    if row.revoked_at is not None:
        return "revoked"
    if _as_utc(row.expires_at) <= datetime.now(timezone.utc):
        return "expired"
    return "active"


def _user_summary(session: Session, row: db.CorporateUser) -> dict[str, object]:
    state = access_state(session, row, groups=latest_authorization_groups(session, row.user_id))
    return {
        "user_id": row.user_uuid,
        "name": row.display_name,
        "corporate_identity": row.canonical_identity,
        "provider": row.provider,
        **state,
        "status": "active" if row.is_active and row.archived_at is None else "disabled",
        "first_sign_in": row.first_successful_sign_in_at,
        "last_sign_in": row.last_successful_sign_in_at,
        "sign_in_count": row.sign_in_count,
        "active_sessions": active_corporate_session_count(session, row.user_id),
        "row_version": row.row_version,
    }


def _get_user(session: Session, user_id: str) -> db.CorporateUser:
    row = session.scalar(select(db.CorporateUser).where(db.CorporateUser.user_uuid == user_id))
    if row is None:
        raise not_found("Corporate user", user_id)
    return row


@router.get("")
def list_users(
    search: str | None = Query(None, max_length=200),
    role: str | None = Query(None, max_length=64),
    status: Literal["active", "disabled"] | None = None,
    provider: str | None = Query(None, max_length=32),
    access_source: Literal["explicit_user_assignment", "corporate_group", "default", "explicit_deny"] | None = None,
    sort: Literal["name", "role", "first_sign_in", "last_sign_in", "status"] = "name",
    direction: Literal["asc", "desc"] = "asc",
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=250),
    session: Session = Depends(get_runtime_session),
    _actor: ActorContext = Depends(require_admin_session("admin.access.manage")),
):
    stmt = select(db.CorporateUser)
    if search:
        needle = f"%{search.strip()}%"
        stmt = stmt.where(or_(db.CorporateUser.display_name.like(needle), db.CorporateUser.canonical_identity.like(needle)))
    if provider:
        stmt = stmt.where(db.CorporateUser.provider == provider)
    if status == "active":
        stmt = stmt.where(db.CorporateUser.is_active.is_(True), db.CorporateUser.archived_at.is_(None))
    elif status == "disabled":
        stmt = stmt.where(or_(db.CorporateUser.is_active.is_(False), db.CorporateUser.archived_at.is_not(None)))
    if access_source == "explicit_user_assignment":
        stmt = stmt.where(db.CorporateUser.explicit_role_code.is_not(None), db.CorporateUser.explicit_denied.is_(False))
    elif access_source == "explicit_deny":
        stmt = stmt.where(db.CorporateUser.explicit_denied.is_(True))
    elif access_source == "default":
        stmt = stmt.where(db.CorporateUser.explicit_role_code.is_(None), db.CorporateUser.explicit_denied.is_(False))
    # The effective role/source can be group-derived and is therefore resolved
    # from safe, bounded session context before sorting or paginating.  EOAT
    # only holds users who have authenticated, not an imported directory.
    rows = session.scalars(stmt.order_by(db.CorporateUser.id.asc())).all()
    items = [_user_summary(session, row) for row in rows]
    if role:
        items = [item for item in items if item["effective_role"] == role]
    if access_source == "corporate_group":
        items = [item for item in items if item["access_source"] == "corporate_group"]
    sort_key = {
        "name": lambda item: str(item["name"]).casefold(),
        "role": lambda item: str(item["effective_role"]),
        "first_sign_in": lambda item: item["first_sign_in"],
        "last_sign_in": lambda item: item["last_sign_in"],
        "status": lambda item: str(item["status"]),
    }[sort]
    items.sort(key=sort_key, reverse=direction == "desc")
    total = len(items)
    start = (page - 1) * page_size
    return {"items": items[start : start + page_size], "page": page, "page_size": page_size, "total": total, "sort": f"{sort}:{direction}"}


@router.get("/{user_id}")
def user_detail(
    user_id: str,
    session: Session = Depends(get_runtime_session),
    _actor: ActorContext = Depends(require_admin_session("admin.access.manage")),
):
    row = _get_user(session, user_id)
    detail = _user_summary(session, row)
    sessions = session.scalars(
        select(db.CorporateAuthenticationSession)
        .where(db.CorporateAuthenticationSession.user_id == row.user_id)
        .order_by(db.CorporateAuthenticationSession.issued_at.desc())
        .limit(100)
    ).all()
    history = session.scalars(
        select(db.AuditEvent)
        .where(db.AuditEvent.entity_type == "CorporateUser", db.AuditEvent.entity_id == str(row.user_uuid))
        .order_by(db.AuditEvent.occurred_at_utc.desc(), db.AuditEvent.id.desc())
        .limit(100)
    ).all()
    return {
        **detail,
        "sessions": [
            {"session_reference": item.session_reference, "issued_at": item.issued_at, "expires_at": item.expires_at, "state": _session_state(item), "provider": item.provider}
            for item in sessions
        ],
        "access_history": [
            {"event_id": item.event_id, "occurred_at": item.occurred_at_utc, "action": item.action, "result": item.result, "reason": item.reason_or_note, "actor": item.actor_display_name, "request_id": item.request_id, "correlation_id": item.correlation_id, "before": item.before_state_json, "after": item.after_state_json}
            for item in history
        ],
    }


@router.post("/{user_id}/access/preview")
def preview_access(
    user_id: str,
    payload: CorporateAccessRequest,
    session: Session = Depends(get_runtime_session),
    actor: ActorContext = Depends(require_admin_session("admin.access.manage")),
):
    row = _get_user(session, user_id)
    if row.user_id == actor.user_id:
        raise APIError(403, "SELF_ACCESS_CHANGE_FORBIDDEN", "An Administrator cannot change their own access.")
    if row.row_version != payload.expected_row_version:
        raise APIError(409, "ROW_VERSION_CONFLICT", "The user access record changed; refresh and review the current state.")
    before, after = preview_explicit_access(session, row, action=payload.action, role_code=payload.role_code)
    return {"user_id": row.user_uuid, "action": payload.action, "before": before, "after": after, "confirmation": f"USER ACCESS {payload.action.upper()} {row.user_uuid}"}


@router.post("/{user_id}/access/commit")
def commit_access(
    user_id: str,
    payload: CorporateAccessRequest,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    session: Session = Depends(get_write_session),
    actor: ActorContext = Depends(require_admin_mutation("admin.access.manage")),
):
    row = _get_user(session, user_id)
    if row.user_id == actor.user_id:
        raise APIError(403, "SELF_ACCESS_CHANGE_FORBIDDEN", "An Administrator cannot change their own access.")
    expected_confirmation = f"USER ACCESS {payload.action.upper()} {row.user_uuid}"
    if payload.confirmation != expected_confirmation:
        raise APIError(422, "CONFIRMATION_MISMATCH", "The typed confirmation does not match the governed action.")

    def commit():
        before, after, revoked_sessions = change_explicit_access(
            session,
            row,
            action=payload.action,
            role_code=payload.role_code,
            reason=payload.reason,
            actor_user_id=actor.user_id,
            expected_row_version=payload.expected_row_version,
        )
        receipt = AuditEventWriter().write_change(
            session,
            actor,
            entity_type="CorporateUser",
            entity_id=row.user_uuid,
            entity_display_id=row.canonical_identity,
            operation=f"admin.users.access.{payload.action}",
            previous=before,
            current={**after, "revoked_session_count": revoked_sessions},
            reason=payload.reason,
            source=AuditSource.WEB,
            action=AuditAction.ROLE_MAPPING_CHANGE,
        )
        return {"user": _user_summary(session, row), "audit_event_id": receipt.event_id, "revoked_session_count": revoked_sessions}

    return idempotent(session, actor, f"admin.users.access.{payload.action}", idempotency_key, {"user_id": user_id, **payload.model_dump()}, commit)


@router.post("/{user_id}/sessions/{session_reference}/revoke")
def revoke_session(
    user_id: str,
    session_reference: str,
    payload: CorporateSessionRevokeRequest,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    session: Session = Depends(get_write_session),
    actor: ActorContext = Depends(require_admin_mutation("admin.session.manage")),
):
    row = _get_user(session, user_id)
    target = session.scalar(
        select(db.CorporateAuthenticationSession).where(
            db.CorporateAuthenticationSession.user_id == row.user_id,
            db.CorporateAuthenticationSession.session_reference == session_reference,
        )
    )
    if target is None:
        raise not_found("Corporate session", session_reference)
    if payload.confirmation != f"REVOKE {session_reference}":
        raise APIError(422, "CONFIRMATION_MISMATCH", "The typed confirmation does not match the governed action.")

    def commit():
        before = {"state": _session_state(target)}
        if target.revoked_at is None:
            target.revoked_at = datetime.now(timezone.utc)
            target.revoke_reason = "admin_access_management"
        receipt = AuditEventWriter().write_change(
            session,
            actor,
            entity_type="CorporateUser",
            entity_id=row.user_uuid,
            entity_display_id=row.canonical_identity,
            operation="admin.users.session.revoke",
            previous=before,
            current={"state": _session_state(target), "session_reference": session_reference},
            reason=payload.reason,
            source=AuditSource.WEB,
            action=AuditAction.SESSION_REVOKED,
        )
        return {"session_reference": session_reference, "audit_event_id": receipt.event_id}

    return idempotent(session, actor, "admin.users.session.revoke", idempotency_key, {"user_id": user_id, "session_reference": session_reference, **payload.model_dump()}, commit)
