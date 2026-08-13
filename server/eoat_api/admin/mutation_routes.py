# ruff: noqa: B008
from __future__ import annotations

import os
from dataclasses import replace
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import models as db
from ..database.session import get_runtime_session, get_write_session
from ..errors import APIError, not_found
from ..security import (
    ADMIN_SESSION_COOKIE,
    ActorContext,
    issue_admin_rehearsal_session,
    require_admin_mutation,
    require_admin_session,
)
from ..write_contracts import EOATPatch, MachinePatch, ToolPatch
from ..write_services import idempotent
from .mutation_contracts import (
    AdminBulkStatusCommit,
    AdminBulkStatusPreview,
    AdminDocumentPatch,
    AdminLifecycleRequest,
    AdminPhotoPatch,
    AdminRelationshipWrite,
    AdminRoleMappingUpdate,
    AdminSessionRevoke,
    AdminSettingUpdate,
    RehearsalSessionIssue,
)
from .mutation_service import (
    asset_record,
    bulk_status_commit,
    bulk_status_preview,
    document_record,
    lifecycle_asset_governed,
    link_relationship_governed,
    list_assets,
    list_documents,
    list_photos,
    list_relationships,
    preview_asset_update,
    setting_view,
    unlink_relationship_governed,
    update_asset_governed,
    update_document_governed,
    update_mapping_governed,
    update_photo_governed,
    update_setting_governed,
)
from .service import AuditEventWriter
from .taxonomy import AuditAction, AuditSource

router = APIRouter(prefix="/api/v1/admin", tags=["admin-governed-editing"])
ASSET_PERMISSIONS = {"eoats": "admin.eoat.edit", "machines": "admin.machine.edit", "tools": "admin.tool.edit"}
ASSET_TYPES = {"eoats": "eoat", "machines": "machine", "tools": "tool"}
ASSET_PATCHES = {"eoats": EOATPatch, "machines": MachinePatch, "tools": ToolPatch}
RELATIONSHIP_TYPES = {"eoat-machine", "eoat-tool", "tool-machine"}


def _confirmation(actual: str, expected: str) -> None:
    if actual.strip() != expected:
        raise APIError(422, "CONFIRMATION_MISMATCH", "The typed confirmation does not match the governed action.")


def _cookie_secure() -> bool:
    return os.getenv("EOAT_API_ADMIN_COOKIE_SECURE", "").strip().casefold() in {"1", "true", "yes", "on"} or os.getenv(
        "EOAT_API_ENVIRONMENT", "development"
    ).strip().casefold() == "staging_local"


@router.post("/session/rehearsal")
def issue_rehearsal_session(
    payload: RehearsalSessionIssue,
    request: Request,
    response: Response,
    session: Session = Depends(get_write_session),
):
    issued = issue_admin_rehearsal_session(session, payload.identity, payload.rehearsal_secret)
    actor = replace(issued.actor, request_id=getattr(request.state, "request_id", None) or str(uuid4()))
    AuditEventWriter().write_change(
        session,
        actor,
        entity_type="Identity",
        entity_id=actor.user_id,
        entity_display_id=actor.identity,
        operation="admin.access.session.issue",
        previous=None,
        current={"session_reference": issued.session_reference, "expires_at": issued.expires_at.isoformat()},
        reason="Development/test Administrator sign-in",
        source=AuditSource.WEB,
        correlation_id=actor.request_id,
        action=AuditAction.LOGIN_SUCCESS,
    )
    max_age = max(1, int((issued.expires_at - datetime.now(timezone.utc)).total_seconds()))
    response.set_cookie(
        ADMIN_SESSION_COOKIE,
        issued.token,
        httponly=True,
        secure=_cookie_secure(),
        samesite="strict",
        max_age=max_age,
        path="/api/v1/admin",
    )
    return {
        "session_reference": issued.session_reference,
        "expires_at": issued.expires_at,
        "csrf_token": issued.csrf_token,
        "actor": {"display_name": issued.actor.display_name, "role": issued.actor.role},
        "environment": os.getenv("EOAT_API_ENVIRONMENT", "development"),
        "audit_event_id": session.scalar(
            select(db.AuditEvent.event_id)
            .where(db.AuditEvent.request_id == actor.request_id)
            .order_by(db.AuditEvent.id.desc())
        ),
    }


@router.post("/data/eoats/bulk-status/preview")
def bulk_preview_route(
    payload: AdminBulkStatusPreview,
    session: Session = Depends(get_runtime_session),
    _actor: ActorContext = Depends(require_admin_session("admin.bulk.execute")),
):
    return bulk_status_preview(session, payload.identifiers, payload.status, payload.expected_versions)


@router.post("/data/eoats/bulk-status/commit")
def bulk_commit_route(
    payload: AdminBulkStatusCommit,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    session: Session = Depends(get_write_session),
    actor: ActorContext = Depends(require_admin_mutation("admin.bulk.execute")),
):
    _confirmation(payload.confirmation, f"BULK STATUS {len(payload.identifiers)}")
    return idempotent(
        session,
        actor,
        "admin.eoat.bulk-status",
        idempotency_key,
        payload.model_dump(),
        lambda: bulk_status_commit(
            session, actor, payload.identifiers, payload.status, payload.expected_versions, payload.reason
        ),
    )


@router.get("/data/{kind}")
def get_assets(
    kind: str,
    search: str | None = Query(None, max_length=200),
    include_archived: bool = False,
    session: Session = Depends(get_runtime_session),
    _actor: ActorContext = Depends(require_admin_session("admin.data.view")),
):
    if kind not in ASSET_TYPES:
        raise not_found("Admin data collection", kind)
    return {"items": list_assets(session, ASSET_TYPES[kind], search, include_archived)}


@router.get("/data/relationships/{relationship_type}")
def get_relationships(
    relationship_type: str,
    include_archived: bool = False,
    session: Session = Depends(get_runtime_session),
    _actor: ActorContext = Depends(require_admin_session("admin.relationship.manage")),
):
    """Register before the generic asset detail route.

    FastAPI selects the first matching path operation. Without this precedence,
    `relationships` is mistaken for an asset collection and the real browser
    relationship workflow receives a misleading 404.
    """
    if relationship_type not in RELATIONSHIP_TYPES:
        raise not_found("relationship type", relationship_type)
    return {"items": list_relationships(session, relationship_type, include_archived)}


@router.get("/data/{kind}/{identifier}")
def get_asset(
    kind: str,
    identifier: str,
    session: Session = Depends(get_runtime_session),
    _actor: ActorContext = Depends(require_admin_session("admin.data.view")),
):
    if kind not in ASSET_TYPES:
        raise not_found("Admin data collection", kind)
    return asset_record(session, ASSET_TYPES[kind], identifier)


@router.post("/data/{kind}/{identifier}/preview")
def preview_asset(
    kind: str,
    identifier: str,
    payload: EOATPatch | MachinePatch | ToolPatch,
    session: Session = Depends(get_write_session),
    _actor: ActorContext = Depends(require_admin_session("admin.data.view")),
):
    if kind not in ASSET_TYPES:
        raise not_found("Admin data collection", kind)
    parsed = ASSET_PATCHES[kind].model_validate(payload.model_dump(exclude_unset=True))
    return preview_asset_update(session, ASSET_TYPES[kind], identifier, parsed.model_dump(exclude_unset=True))


@router.patch("/data/{kind}/{identifier}")
def update_asset_route(
    kind: str,
    identifier: str,
    payload: EOATPatch | MachinePatch | ToolPatch,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    session: Session = Depends(get_write_session),
    actor: ActorContext = Depends(require_admin_mutation("admin.data.view")),
):
    if kind not in ASSET_TYPES:
        raise not_found("Admin data collection", kind)
    permission = ASSET_PERMISSIONS[kind]
    if not actor.permits(permission):
        raise APIError(403, "PERMISSION_DENIED", "The authenticated identity does not have this capability.")
    parsed = ASSET_PATCHES[kind].model_validate(payload.model_dump(exclude_unset=True))
    values = parsed.model_dump(exclude_unset=True)
    return idempotent(
        session,
        actor,
        f"admin.{ASSET_TYPES[kind]}.update",
        idempotency_key,
        {"identifier": identifier, **values},
        lambda: update_asset_governed(session, actor, ASSET_TYPES[kind], identifier, values.copy()),
    )


@router.patch("/data/{kind}/{identifier}/correction")
def correct_asset_route(
    kind: str,
    identifier: str,
    payload: EOATPatch | MachinePatch | ToolPatch,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    session: Session = Depends(get_write_session),
    actor: ActorContext = Depends(require_admin_mutation("admin.data.view")),
):
    if kind not in ASSET_TYPES:
        raise not_found("Admin data collection", kind)
    if not actor.permits(ASSET_PERMISSIONS[kind]):
        raise APIError(403, "PERMISSION_DENIED", "The authenticated identity does not have this capability.")
    parsed = ASSET_PATCHES[kind].model_validate(payload.model_dump(exclude_unset=True))
    values = parsed.model_dump(exclude_unset=True)
    return idempotent(
        session,
        actor,
        f"admin.{ASSET_TYPES[kind]}.correction",
        idempotency_key,
        {"identifier": identifier, **values},
        lambda: update_asset_governed(session, actor, ASSET_TYPES[kind], identifier, values.copy(), correction=True),
    )


@router.post("/data/{kind}/{identifier}/{action}")
def lifecycle_asset_route(
    kind: str,
    identifier: str,
    action: str,
    payload: AdminLifecycleRequest,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    session: Session = Depends(get_write_session),
    actor: ActorContext = Depends(require_admin_mutation("admin.asset.archive")),
):
    if kind not in ASSET_TYPES or action not in {"archive", "restore"}:
        raise not_found("Admin lifecycle operation", f"{kind}/{action}")
    _confirmation(payload.confirmation, f"{action.upper()} {identifier}")
    values = payload.model_dump()
    return idempotent(
        session,
        actor,
        f"admin.{ASSET_TYPES[kind]}.{action}",
        idempotency_key,
        {"identifier": identifier, "action": action, **values},
        lambda: lifecycle_asset_governed(
            session,
            actor,
            ASSET_TYPES[kind],
            identifier,
            payload.expected_row_version,
            payload.reason,
            archived=action == "archive",
        ),
    )


@router.get("/documents")
def get_documents(
    search: str | None = Query(None, max_length=200),
    include_archived: bool = False,
    session: Session = Depends(get_runtime_session),
    _actor: ActorContext = Depends(require_admin_session("admin.document.manage")),
):
    return {"items": list_documents(session, search, include_archived)}


@router.get("/documents/{document_id}")
def get_document(
    document_id: int,
    session: Session = Depends(get_runtime_session),
    _actor: ActorContext = Depends(require_admin_session("admin.document.manage")),
):
    return document_record(session, document_id)


@router.patch("/documents/{document_id}")
def update_document_route(
    document_id: int,
    payload: AdminDocumentPatch,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    session: Session = Depends(get_write_session),
    actor: ActorContext = Depends(require_admin_mutation("admin.document.manage")),
):
    values = payload.model_dump(exclude_unset=True)
    return idempotent(
        session,
        actor,
        "admin.document.metadata.update",
        idempotency_key,
        {"document_id": document_id, **values},
        lambda: update_document_governed(session, actor, document_id, values.copy()),
    )


@router.post("/documents/{document_id}/archive")
def archive_document_route(
    document_id: int,
    payload: AdminLifecycleRequest,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    session: Session = Depends(get_write_session),
    actor: ActorContext = Depends(require_admin_mutation("admin.document.manage")),
):
    _confirmation(payload.confirmation, f"ARCHIVE DOCUMENT {document_id}")
    values = {"expected_row_version": payload.expected_row_version, "reason": payload.reason}
    return idempotent(
        session,
        actor,
        "admin.document.archive",
        idempotency_key,
        {"document_id": document_id, **values},
        lambda: update_document_governed(session, actor, document_id, values, archive=True),
    )


@router.get("/photos")
def get_photos(
    include_archived: bool = False,
    session: Session = Depends(get_runtime_session),
    _actor: ActorContext = Depends(require_admin_session("admin.document.manage")),
):
    return {"items": list_photos(session, include_archived)}


@router.patch("/photos/{photo_id}")
def update_photo_route(
    photo_id: int,
    payload: AdminPhotoPatch,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    session: Session = Depends(get_write_session),
    actor: ActorContext = Depends(require_admin_mutation("admin.document.manage")),
):
    values = payload.model_dump(exclude_unset=True)
    return idempotent(
        session,
        actor,
        "admin.photo.metadata.update",
        idempotency_key,
        {"photo_id": photo_id, **values},
        lambda: update_photo_governed(session, actor, photo_id, values.copy()),
    )


@router.post("/photos/{photo_id}/archive")
def archive_photo_route(
    photo_id: int,
    payload: AdminLifecycleRequest,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    session: Session = Depends(get_write_session),
    actor: ActorContext = Depends(require_admin_mutation("admin.document.manage")),
):
    _confirmation(payload.confirmation, f"ARCHIVE PHOTO {photo_id}")
    values = {"expected_row_version": payload.expected_row_version, "reason": payload.reason}
    return idempotent(
        session,
        actor,
        "admin.photo.archive",
        idempotency_key,
        {"photo_id": photo_id, **values},
        lambda: update_photo_governed(session, actor, photo_id, values, archive=True),
    )


@router.post("/data/relationships/{relationship_type}")
def link_relationship_route(
    relationship_type: str,
    payload: AdminRelationshipWrite,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    session: Session = Depends(get_write_session),
    actor: ActorContext = Depends(require_admin_mutation("admin.relationship.manage")),
):
    if relationship_type not in RELATIONSHIP_TYPES:
        raise not_found("relationship type", relationship_type)
    _confirmation(payload.confirmation, f"LINK {relationship_type}")
    values = payload.model_dump(exclude_unset=True)
    return idempotent(
        session,
        actor,
        "admin.relationship.link",
        idempotency_key,
        {"relationship_type": relationship_type, **values},
        lambda: link_relationship_governed(session, actor, relationship_type, values.copy()),
    )


@router.post("/data/relationships/{relationship_type}/{relationship_id}/unlink")
def unlink_relationship_route(
    relationship_type: str,
    relationship_id: int,
    payload: AdminLifecycleRequest,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    session: Session = Depends(get_write_session),
    actor: ActorContext = Depends(require_admin_mutation("admin.relationship.manage")),
):
    if relationship_type not in RELATIONSHIP_TYPES:
        raise not_found("relationship type", relationship_type)
    _confirmation(payload.confirmation, f"UNLINK {relationship_type}:{relationship_id}")
    return idempotent(
        session,
        actor,
        "admin.relationship.unlink",
        idempotency_key,
        {"relationship_type": relationship_type, "relationship_id": relationship_id, **payload.model_dump()},
        lambda: unlink_relationship_governed(
            session, actor, relationship_type, relationship_id, payload.expected_row_version, payload.reason
        ),
    )


@router.get("/settings")
def list_settings(
    session: Session = Depends(get_runtime_session),
    _actor: ActorContext = Depends(require_admin_session("admin.settings.edit")),
):
    return {"items": [setting_view(row) for row in session.scalars(select(db.SystemSetting).order_by(db.SystemSetting.setting_key))]}


@router.patch("/settings/{key}")
def update_setting_route(
    key: str,
    payload: AdminSettingUpdate,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    session: Session = Depends(get_write_session),
    actor: ActorContext = Depends(require_admin_mutation("admin.settings.edit")),
):
    return idempotent(
        session,
        actor,
        "admin.setting.update",
        idempotency_key,
        {"key": key, **payload.model_dump()},
        lambda: update_setting_governed(session, actor, key, payload.value, payload.expected_row_version, payload.reason),
    )


@router.get("/access/test-mappings")
def list_test_mappings(
    session: Session = Depends(get_runtime_session),
    _actor: ActorContext = Depends(require_admin_session("admin.access.manage")),
):
    rows = session.scalars(
        select(db.DevelopmentIdentityMapping).where(db.DevelopmentIdentityMapping.is_active.is_(True)).order_by(
            db.DevelopmentIdentityMapping.environment, db.DevelopmentIdentityMapping.identity
        )
    )
    return {"items": [{"identity": row.identity, "environment": row.environment, "role_code": row.role_code, "row_version": row.row_version} for row in rows]}


@router.patch("/access/test-mappings/{identity}")
def update_test_mapping_route(
    identity: str,
    payload: AdminRoleMappingUpdate,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    session: Session = Depends(get_write_session),
    actor: ActorContext = Depends(require_admin_mutation("admin.access.manage")),
):
    return idempotent(
        session,
        actor,
        "admin.access.test-mapping.update",
        idempotency_key,
        {"identity": identity, **payload.model_dump()},
        lambda: update_mapping_governed(
            session,
            actor,
            identity,
            payload.role_code,
            payload.expected_row_version,
            payload.reason,
            os.getenv("EOAT_API_ENVIRONMENT", "development").strip().casefold(),
        ),
    )


@router.get("/access/sessions")
def list_rehearsal_sessions(
    session: Session = Depends(get_runtime_session),
    _actor: ActorContext = Depends(require_admin_session("admin.session.manage")),
):
    rows = session.scalars(select(db.AdminRehearsalSession).order_by(db.AdminRehearsalSession.issued_at.desc()).limit(100))
    return {"items": [{"session_reference": row.session_reference, "user_id": row.user_id, "environment": row.environment, "issued_at": row.issued_at, "expires_at": row.expires_at, "last_seen_at": row.last_seen_at, "revoked_at": row.revoked_at} for row in rows]}


@router.post("/access/sessions/{session_reference}/revoke")
def revoke_rehearsal_session(
    session_reference: str,
    payload: AdminSessionRevoke,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    session: Session = Depends(get_write_session),
    actor: ActorContext = Depends(require_admin_mutation("admin.session.manage")),
):
    _confirmation(payload.confirmation, f"REVOKE {session_reference}")

    def execute():
        record = session.scalar(
            select(db.AdminRehearsalSession)
            .where(db.AdminRehearsalSession.session_reference == session_reference)
            .with_for_update()
        )
        if record is None:
            raise not_found("rehearsal session", session_reference)
        if record.revoked_at is None:
            record.revoked_at = datetime.now(timezone.utc)
            record.revoked_by_user_id = actor.user_id
            record.revoke_reason = payload.reason
        audit = AuditEventWriter().write_change(
            session,
            actor,
            entity_type="Identity",
            entity_id=record.id,
            entity_display_id=session_reference,
            operation="admin.access.session.revoke",
            previous={"revoked": False},
            current={"revoked": True},
            reason=payload.reason,
            source=AuditSource.WEB,
            correlation_id=actor.request_id,
            action=AuditAction.SESSION_REVOKED,
        )
        return {"session_reference": session_reference, "revoked": True, "audit_event_id": audit.event_id, "correlation_id": actor.request_id, "request_id": actor.request_id}

    return idempotent(
        session,
        actor,
        "admin.access.session.revoke",
        idempotency_key,
        {"session_reference": session_reference, **payload.model_dump()},
        execute,
    )
