# ruff: noqa: B008
from __future__ import annotations

import os
import re
from base64 import b64decode
from binascii import Error as Base64Error
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .database import models as db
from .database.session import get_write_session
from .errors import APIError
from .security import ActorContext, require
from .write_contracts import (
    AnnotationCreate,
    AnnotationPatch,
    ApplicationInstanceHeartbeat,
    ApplicationInstanceRegistration,
    AuditCreate,
    AuditPatch,
    CompatibilityWrite,
    DocumentCreate,
    DocumentPatch,
    EOATCreate,
    EOATPatch,
    ExpectedVersion,
    InstallationClose,
    MachineCreate,
    MachinePatch,
    MaintenanceCreate,
    MaintenancePatch,
    MarkLocationUnknown,
    MoveToMachine,
    MoveToStorage,
    PhotoCreate,
    PhotoPatch,
    RobotCreate,
    RobotPatch,
    TagAssignmentArchiveBatch,
    TagAssignmentWrite,
    TagCreate,
    TagPatch,
    ToolCreate,
    ToolPatch,
)
from .write_services import (
    archive_compatibility,
    archive_tag_assignments,
    assign_tag,
    close_installation,
    create_annotation,
    create_asset,
    create_audit,
    create_document,
    create_global_annotation,
    create_maintenance,
    create_or_get_annotation_target,
    create_photo,
    create_tag,
    idempotent,
    link_annotation_target,
    mark_location_unknown,
    move_to_machine,
    move_to_storage,
    public_record,
    register_instance,
    remove_tag,
    resolve_target,
    set_asset_archived,
    set_profile_photo,
    supersede_document,
    unlink_annotation_target,
    update_annotation,
    update_asset,
    update_audit,
    update_document,
    update_maintenance,
    update_photo,
    update_tag,
    write_compatibility,
)

router = APIRouter(prefix="/api/v1")

_UPLOAD_NAME = re.compile(r"[^A-Za-z0-9._ -]+")
_MAX_BROWSER_UPLOAD_BYTES = 20 * 1024 * 1024


class BrowserMediaUpload(BaseModel):
    entity_type: str = Field(min_length=1, max_length=32)
    entity_identifier: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=255)
    file_name: str = Field(min_length=1, max_length=255)
    content_base64: str = Field(min_length=1, max_length=28 * 1024 * 1024)
    media_kind: str = "document"
    document_type: str = "document"
    description: str | None = None
    revision: str | None = None
    relationship_type: str = "attachment"
    caption: str | None = None
    photo_view_type: str | None = None
    mime_type: str | None = None


def body(model, *, exclude_unset: bool = False) -> dict[str, Any]:
    return model.model_dump(exclude_unset=exclude_unset)


def _browser_upload_root() -> Path:
    """Return a server-owned writable media root, or fail closed."""
    configured = os.getenv("EOAT_WEB_UPLOAD_ROOT", "").strip()
    if not configured:
        raise APIError(503, "WEB_UPLOAD_UNAVAILABLE", "Browser uploads are not configured for this environment.")
    try:
        root = Path(configured).expanduser().resolve(strict=True)
    except OSError:
        raise APIError(503, "WEB_UPLOAD_UNAVAILABLE", "Browser uploads are not configured for this environment.") from None
    if not root.is_dir():
        raise APIError(503, "WEB_UPLOAD_UNAVAILABLE", "Browser uploads are not configured for this environment.")
    document_roots = [Path(item).expanduser().resolve() for item in os.getenv("EOAT_DOCUMENT_ROOTS", "").split(os.pathsep) if item.strip()]
    content_roots = [Path(item).expanduser().resolve() for item in os.getenv("EOAT_WEB_CONTENT_ROOTS", "").split(os.pathsep) if item.strip()]
    if not document_roots or not content_roots or not any(root.is_relative_to(item) for item in document_roots) or not any(root.is_relative_to(item) for item in content_roots):
        raise APIError(503, "WEB_UPLOAD_UNAVAILABLE", "Browser uploads are not configured for this environment.")
    return root


def _persist_browser_upload(file_name: str, content_base64: str, root: Path) -> Path:
    supplied = Path(file_name).name
    safe_name = _UPLOAD_NAME.sub("-", supplied).strip(" .-") or "upload.bin"
    target = root / f"{uuid4().hex}-{safe_name}"
    try:
        content = b64decode(content_base64, validate=True)
    except (Base64Error, ValueError):
        raise APIError(422, "INVALID_MEDIA_CONTENT", "The selected file could not be decoded.") from None
    if len(content) > _MAX_BROWSER_UPLOAD_BYTES:
        raise APIError(413, "WEB_UPLOAD_TOO_LARGE", "The selected file exceeds the 20 MB browser upload limit.")
    try:
        target.write_bytes(content)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return target


@router.post("/eoats")
def create_eoat_route(
    payload: EOATCreate,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    session: Session = Depends(get_write_session),
    actor: ActorContext = Depends(require("asset.write")),
):
    values = body(payload)
    return idempotent(
        session,
        actor,
        "eoat.create",
        idempotency_key,
        values,
        lambda: create_asset(session, actor, "eoat", values.copy()),
    )


@router.patch("/eoats/{identifier}")
def update_eoat_route(
    identifier: str,
    payload: EOATPatch,
    session: Session = Depends(get_write_session),
    actor: ActorContext = Depends(require("asset.write")),
):
    return update_asset(session, actor, "eoat", identifier, body(payload, exclude_unset=True))


@router.post("/eoats/{identifier}/archive")
def archive_eoat_route(
    identifier: str,
    payload: ExpectedVersion,
    session: Session = Depends(get_write_session),
    actor: ActorContext = Depends(require("*")),
):
    return set_asset_archived(session, actor, "eoat", identifier, payload.expected_row_version, payload.reason, True)


@router.post("/eoats/{identifier}/restore")
def restore_eoat_route(
    identifier: str,
    payload: ExpectedVersion,
    session: Session = Depends(get_write_session),
    actor: ActorContext = Depends(require("*")),
):
    return set_asset_archived(session, actor, "eoat", identifier, payload.expected_row_version, payload.reason, False)


@router.post("/machines")
def create_machine_route(
    payload: MachineCreate,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    session: Session = Depends(get_write_session),
    actor: ActorContext = Depends(require("asset.write")),
):
    values = body(payload)
    return idempotent(
        session,
        actor,
        "machine.create",
        idempotency_key,
        values,
        lambda: create_asset(session, actor, "machine", values.copy()),
    )


@router.patch("/machines/{identifier}")
def update_machine_route(
    identifier: str,
    payload: MachinePatch,
    session: Session = Depends(get_write_session),
    actor: ActorContext = Depends(require("asset.write")),
):
    return update_asset(session, actor, "machine", identifier, body(payload, exclude_unset=True))


@router.post("/machines/{identifier}/archive")
def archive_machine_route(
    identifier: str,
    payload: ExpectedVersion,
    session: Session = Depends(get_write_session),
    actor: ActorContext = Depends(require("*")),
):
    return set_asset_archived(session, actor, "machine", identifier, payload.expected_row_version, payload.reason, True)


@router.post("/machines/{identifier}/restore")
def restore_machine_route(
    identifier: str,
    payload: ExpectedVersion,
    session: Session = Depends(get_write_session),
    actor: ActorContext = Depends(require("*")),
):
    return set_asset_archived(
        session, actor, "machine", identifier, payload.expected_row_version, payload.reason, False
    )


@router.post("/tools")
def create_tool_route(
    payload: ToolCreate,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    session: Session = Depends(get_write_session),
    actor: ActorContext = Depends(require("asset.write")),
):
    values = body(payload)
    return idempotent(
        session,
        actor,
        "tool.create",
        idempotency_key,
        values,
        lambda: create_asset(session, actor, "tool", values.copy()),
    )


@router.patch("/tools/{identifier}")
def update_tool_route(
    identifier: str,
    payload: ToolPatch,
    session: Session = Depends(get_write_session),
    actor: ActorContext = Depends(require("asset.write")),
):
    return update_asset(session, actor, "tool", identifier, body(payload, exclude_unset=True))


@router.post("/tools/{identifier}/archive")
def archive_tool_route(
    identifier: str,
    payload: ExpectedVersion,
    session: Session = Depends(get_write_session),
    actor: ActorContext = Depends(require("*")),
):
    return set_asset_archived(session, actor, "tool", identifier, payload.expected_row_version, payload.reason, True)


@router.post("/tools/{identifier}/restore")
def restore_tool_route(
    identifier: str,
    payload: ExpectedVersion,
    session: Session = Depends(get_write_session),
    actor: ActorContext = Depends(require("*")),
):
    return set_asset_archived(session, actor, "tool", identifier, payload.expected_row_version, payload.reason, False)


@router.get("/robots")
def list_robots(active: bool | None = True, session: Session = Depends(get_write_session)):
    stmt = select(db.Robot)
    if active is not None:
        stmt = stmt.where(db.Robot.is_active.is_(active))
    return [public_record(row) for row in session.scalars(stmt.order_by(db.Robot.robot_number))]


@router.get("/robots/{identifier}")
def get_robot(identifier: str, session: Session = Depends(get_write_session)):
    value = session.scalar(select(db.Robot).where(db.Robot.robot_number == identifier))
    if value is None:
        raise APIError(404, "NOT_FOUND", f"Robot '{identifier}' was not found.")
    return public_record(value)


@router.post("/robots")
def create_robot_route(
    payload: RobotCreate,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    session: Session = Depends(get_write_session),
    actor: ActorContext = Depends(require("asset.write")),
):
    values = body(payload)
    return idempotent(
        session,
        actor,
        "robot.create",
        idempotency_key,
        values,
        lambda: create_asset(session, actor, "robot", values.copy()),
    )


@router.patch("/robots/{identifier}")
def update_robot_route(
    identifier: str,
    payload: RobotPatch,
    session: Session = Depends(get_write_session),
    actor: ActorContext = Depends(require("asset.write")),
):
    return update_asset(session, actor, "robot", identifier, body(payload, exclude_unset=True))


@router.post("/robots/{identifier}/archive")
def archive_robot_route(
    identifier: str,
    payload: ExpectedVersion,
    session: Session = Depends(get_write_session),
    actor: ActorContext = Depends(require("*")),
):
    return set_asset_archived(session, actor, "robot", identifier, payload.expected_row_version, payload.reason, True)


@router.post("/robots/{identifier}/restore")
def restore_robot_route(
    identifier: str,
    payload: ExpectedVersion,
    session: Session = Depends(get_write_session),
    actor: ActorContext = Depends(require("*")),
):
    return set_asset_archived(session, actor, "robot", identifier, payload.expected_row_version, payload.reason, False)


for relationship_type in ("eoat-machine", "eoat-tool", "tool-machine"):

    def _register_compatibility_routes(kind: str):
        @router.post(f"/compatibility/{kind}", name=f"create_{kind.replace('-', '_')}")
        def create_relationship(
            payload: CompatibilityWrite,
            session: Session = Depends(get_write_session),
            actor: ActorContext = Depends(require("compatibility.write")),
        ):
            return write_compatibility(session, actor, kind, body(payload, exclude_unset=True))

        @router.patch(f"/compatibility/{kind}/{{relationship_id}}", name=f"update_{kind.replace('-', '_')}")
        def update_relationship(
            relationship_id: int,
            payload: CompatibilityWrite,
            session: Session = Depends(get_write_session),
            actor: ActorContext = Depends(require("compatibility.write")),
        ):
            return write_compatibility(session, actor, kind, body(payload, exclude_unset=True), relationship_id)

        @router.post(f"/compatibility/{kind}/{{relationship_id}}/archive", name=f"archive_{kind.replace('-', '_')}")
        def archive_relationship(
            relationship_id: int,
            payload: ExpectedVersion,
            session: Session = Depends(get_write_session),
            actor: ActorContext = Depends(require("compatibility.write")),
        ):
            return archive_compatibility(
                session, actor, kind, relationship_id, payload.expected_row_version, payload.reason
            )

    _register_compatibility_routes(relationship_type)


@router.post("/eoats/{identifier}/move-to-machine")
def move_to_machine_route(
    identifier: str,
    payload: MoveToMachine,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    session: Session = Depends(get_write_session),
    actor: ActorContext = Depends(require("installation.write")),
):
    values = body(payload)
    return idempotent(
        session,
        actor,
        "eoat.move_to_machine",
        idempotency_key,
        {"identifier": identifier, **values},
        lambda: move_to_machine(session, actor, identifier, values.copy()),
    )


@router.post("/eoats/{identifier}/move-to-storage")
def move_to_storage_route(
    identifier: str,
    payload: MoveToStorage,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    session: Session = Depends(get_write_session),
    actor: ActorContext = Depends(require("installation.write")),
):
    values = body(payload)
    return idempotent(
        session,
        actor,
        "eoat.move_to_storage",
        idempotency_key,
        {"identifier": identifier, **values},
        lambda: move_to_storage(session, actor, identifier, values.copy()),
    )


@router.post("/eoats/{identifier}/mark-location-unknown")
def mark_location_unknown_route(
    identifier: str,
    payload: MarkLocationUnknown,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    session: Session = Depends(get_write_session),
    actor: ActorContext = Depends(require("installation.write")),
):
    values = body(payload)
    return idempotent(
        session,
        actor,
        "eoat.location_unknown",
        idempotency_key,
        {"identifier": identifier, **values},
        lambda: mark_location_unknown(session, actor, identifier, payload.expected_row_version, payload.reason),
    )


@router.post("/installations")
def create_installation_route(
    payload: dict[str, Any],
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    session: Session = Depends(get_write_session),
    actor: ActorContext = Depends(require("installation.write")),
):
    identifier = str(payload.pop("eoat_identifier", ""))
    validated = MoveToMachine.model_validate(payload)
    values = body(validated)
    return idempotent(
        session,
        actor,
        "installation.create",
        idempotency_key,
        {"identifier": identifier, **values},
        lambda: move_to_machine(session, actor, identifier, values.copy()),
    )


@router.post("/installations/{installation_id}/close")
def close_installation_route(
    installation_id: int,
    payload: InstallationClose,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    session: Session = Depends(get_write_session),
    actor: ActorContext = Depends(require("installation.write")),
):
    values = body(payload)
    return idempotent(
        session,
        actor,
        "installation.close",
        idempotency_key,
        {"installation_id": installation_id, **values},
        lambda: close_installation(session, actor, installation_id, values.copy()),
    )


@router.post("/audits")
def create_audit_route(
    payload: AuditCreate,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    session: Session = Depends(get_write_session),
    actor: ActorContext = Depends(require("audit.write")),
):
    values = body(payload)
    return idempotent(
        session, actor, "audit.create", idempotency_key, values, lambda: create_audit(session, actor, values.copy())
    )


@router.get("/audits/by-identifier/{audit_identifier}")
def get_audit_by_identifier(audit_identifier: str, session: Session = Depends(get_write_session)):
    record = session.scalar(select(db.AuditRecord).where(db.AuditRecord.audit_identifier == audit_identifier))
    if record is None:
        raise APIError(404, "NOT_FOUND", f"Audit '{audit_identifier}' was not found.")
    return public_record(record)


@router.patch("/audits/{audit_id}")
def update_audit_route(
    audit_id: int,
    payload: AuditPatch,
    session: Session = Depends(get_write_session),
    actor: ActorContext = Depends(require("audit.write")),
):
    return update_audit(session, actor, audit_id, body(payload, exclude_unset=True))


@router.post("/audits/{audit_id}/complete")
def complete_audit_route(
    audit_id: int,
    payload: ExpectedVersion,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    session: Session = Depends(get_write_session),
    actor: ActorContext = Depends(require("audit.write")),
):
    values = body(payload)
    return idempotent(
        session,
        actor,
        "audit.complete",
        idempotency_key,
        {"audit_id": audit_id, **values},
        lambda: update_audit(session, actor, audit_id, values.copy(), complete=True),
    )


@router.post("/audits/{audit_id}/archive")
def archive_audit_route(
    audit_id: int,
    payload: ExpectedVersion,
    session: Session = Depends(get_write_session),
    actor: ActorContext = Depends(require("*")),
):
    return update_audit(session, actor, audit_id, body(payload), archive=True)


@router.post("/maintenance-events")
def create_maintenance_route(
    payload: MaintenanceCreate,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    session: Session = Depends(get_write_session),
    actor: ActorContext = Depends(require("maintenance.write")),
):
    values = body(payload)
    return idempotent(
        session,
        actor,
        "maintenance.create",
        idempotency_key,
        values,
        lambda: create_maintenance(session, actor, values.copy()),
    )


@router.patch("/maintenance-events/{event_id}")
def update_maintenance_route(
    event_id: int,
    payload: MaintenancePatch,
    session: Session = Depends(get_write_session),
    actor: ActorContext = Depends(require("maintenance.write")),
):
    return update_maintenance(session, actor, event_id, body(payload, exclude_unset=True))


@router.post("/maintenance-events/{event_id}/complete")
def complete_maintenance_route(
    event_id: int,
    payload: ExpectedVersion,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    session: Session = Depends(get_write_session),
    actor: ActorContext = Depends(require("maintenance.write")),
):
    values = body(payload)
    return idempotent(
        session,
        actor,
        "maintenance.complete",
        idempotency_key,
        {"event_id": event_id, **values},
        lambda: update_maintenance(session, actor, event_id, values.copy(), complete=True),
    )


@router.post("/documents")
def create_document_route(
    payload: DocumentCreate,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    session: Session = Depends(get_write_session),
    actor: ActorContext = Depends(require("document.write")),
):
    values = body(payload)
    return idempotent(
        session,
        actor,
        "document.create",
        idempotency_key,
        values,
        lambda: create_document(session, actor, values.copy()),
    )


@router.patch("/documents/{document_id}")
def update_document_route(
    document_id: int,
    payload: DocumentPatch,
    session: Session = Depends(get_write_session),
    actor: ActorContext = Depends(require("document.write")),
):
    return update_document(session, actor, document_id, body(payload, exclude_unset=True))


@router.post("/documents/{document_id}/archive")
def archive_document_route(
    document_id: int,
    payload: ExpectedVersion,
    session: Session = Depends(get_write_session),
    actor: ActorContext = Depends(require("document.write")),
):
    return update_document(session, actor, document_id, body(payload), archive=True)


@router.post("/documents/{document_id}/supersede")
def supersede_document_route(
    document_id: int,
    payload: DocumentCreate,
    expected_row_version: int = Query(..., ge=1),
    reason: str | None = None,
    session: Session = Depends(get_write_session),
    actor: ActorContext = Depends(require("document.write")),
):
    return supersede_document(session, actor, document_id, expected_row_version, body(payload), reason)


@router.post("/photos")
def create_photo_route(
    payload: PhotoCreate,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    session: Session = Depends(get_write_session),
    actor: ActorContext = Depends(require("document.write")),
):
    values = body(payload)
    return idempotent(
        session, actor, "photo.create", idempotency_key, values, lambda: create_photo(session, actor, values.copy())
    )


@router.patch("/photos/{photo_id}")
def update_photo_route(
    photo_id: int,
    payload: PhotoPatch,
    session: Session = Depends(get_write_session),
    actor: ActorContext = Depends(require("document.write")),
):
    return update_photo(session, actor, photo_id, body(payload, exclude_unset=True))


@router.post("/photos/{photo_id}/archive")
def archive_photo_route(
    photo_id: int,
    payload: ExpectedVersion,
    session: Session = Depends(get_write_session),
    actor: ActorContext = Depends(require("document.write")),
):
    return update_photo(session, actor, photo_id, body(payload), archive=True)


@router.post("/photos/{photo_id}/set-profile")
def set_profile_photo_route(
    photo_id: int,
    payload: ExpectedVersion,
    session: Session = Depends(get_write_session),
    actor: ActorContext = Depends(require("document.write")),
):
    return set_profile_photo(
        session,
        actor,
        photo_id,
        payload.expected_row_version,
        payload.reason,
    )


@router.post("/web-media/upload")
def upload_browser_media_route(
    payload: BrowserMediaUpload,
    session: Session = Depends(get_write_session),
    actor: ActorContext = Depends(require("document.write")),
):
    """Store a browser-selected file in a controlled server root without exposing its path."""
    if payload.media_kind not in {"document", "photo"}:
        raise APIError(422, "INVALID_MEDIA_KIND", "Media kind must be document or photo.")
    target_entity = resolve_target(session, payload.entity_type, payload.entity_identifier)
    root = _browser_upload_root()
    stored = _persist_browser_upload(payload.file_name, payload.content_base64, root)
    values = {
        "document_type": "photo" if payload.media_kind == "photo" else payload.document_type,
        "title": payload.title,
        "description": payload.description,
        "revision": payload.revision,
        "storage_path": str(stored),
        "mime_type": payload.mime_type,
        "entity_type": payload.entity_type,
        "entity_id": target_entity.id,
        "relationship_type": payload.relationship_type,
    }
    try:
        result = (
            create_photo(session, actor, {**values, "caption": payload.caption, "photo_view_type": payload.photo_view_type})
            if payload.media_kind == "photo"
            else create_document(session, actor, values)
        )
    except Exception:
        stored.unlink(missing_ok=True)
        raise
    document = result["document"] if payload.media_kind == "photo" else result
    return {
        "document_uuid": document["document_uuid"],
        "title": document["title"],
        "file_name": document["file_name"],
        "row_version": document["row_version"],
        "media_kind": payload.media_kind,
    }


@router.get("/tags")
def list_tags(include_archived: bool = False, session: Session = Depends(get_write_session)):
    stmt = select(db.Tag)
    if not include_archived:
        stmt = stmt.where(db.Tag.is_active.is_(True))
    return [public_record(row) for row in session.scalars(stmt.order_by(db.Tag.display_name))]


@router.get("/annotation-targets")
def list_annotation_targets(
    audit_identifier: str | None = None,
    machine_identifier: str | None = None,
    field_key: str | None = None,
    session: Session = Depends(get_write_session),
):
    stmt = select(db.AnnotationTarget)
    if audit_identifier:
        stmt = stmt.where(db.AnnotationTarget.audit_identifier == audit_identifier)
    if machine_identifier:
        stmt = stmt.where(db.AnnotationTarget.machine_identifier == machine_identifier)
    if field_key:
        stmt = stmt.where(db.AnnotationTarget.field_key == field_key)
    return [
        public_record(row)
        for row in session.scalars(stmt.order_by(db.AnnotationTarget.target_type, db.AnnotationTarget.target_label))
    ]


@router.get("/annotation-targets/{target_id}")
def get_annotation_target(target_id: str, session: Session = Depends(get_write_session)):
    return public_record(resolve_target(session, "annotation_target", target_id))


@router.post("/annotation-targets")
def create_annotation_target_route(
    payload: dict[str, Any],
    session: Session = Depends(get_write_session),
    actor: ActorContext = Depends(require("annotation.write")),
):
    if not payload.get("target_uuid") or not payload.get("target_type"):
        raise APIError(422, "VALIDATION_ERROR", "target_uuid and target_type are required.")
    return create_or_get_annotation_target(session, actor, payload)


@router.post("/tags")
def create_tag_route(
    payload: TagCreate,
    session: Session = Depends(get_write_session),
    actor: ActorContext = Depends(require("tag.manage")),
):
    return create_tag(session, actor, body(payload))


@router.patch("/tags/{tag_id}")
def update_tag_route(
    tag_id: int,
    payload: TagPatch,
    session: Session = Depends(get_write_session),
    actor: ActorContext = Depends(require("tag.manage")),
):
    return update_tag(session, actor, tag_id, body(payload, exclude_unset=True))


@router.post("/tags/{tag_id}/archive")
def archive_tag_route(
    tag_id: int,
    payload: ExpectedVersion,
    session: Session = Depends(get_write_session),
    actor: ActorContext = Depends(require("tag.manage")),
):
    return update_tag(session, actor, tag_id, body(payload), archive=True)


@router.get("/entities/{entity_type}/{entity_id}/tags")
def entity_tags(entity_type: str, entity_id: str, session: Session = Depends(get_write_session)):
    target = resolve_target(session, entity_type, entity_id)
    rows = session.scalars(
        select(db.EntityTag).where(
            db.EntityTag.entity_type == entity_type,
            db.EntityTag.entity_id == target.id,
            db.EntityTag.removed_at.is_(None),
        )
    ).all()
    return [public_record(row) for row in rows]


@router.post("/entities/{entity_type}/{entity_id}/tags/{tag_id}")
def assign_tag_route(
    entity_type: str,
    entity_id: str,
    tag_id: int,
    payload: TagAssignmentWrite,
    session: Session = Depends(get_write_session),
    actor: ActorContext = Depends(require("tag.assign")),
):
    return assign_tag(session, actor, entity_type, entity_id, tag_id, payload.comment)


@router.delete("/entities/{entity_type}/{entity_id}/tags/{tag_id}")
def remove_tag_route(
    entity_type: str,
    entity_id: str,
    tag_id: int,
    payload: TagAssignmentWrite | None = None,
    session: Session = Depends(get_write_session),
    actor: ActorContext = Depends(require("tag.assign")),
):
    return remove_tag(session, actor, entity_type, entity_id, tag_id, payload.expected_row_version if payload else None)


@router.get("/entities/{entity_type}/{entity_id}/annotations")
def entity_annotations(entity_type: str, entity_id: str, session: Session = Depends(get_write_session)):
    target = resolve_target(session, entity_type, entity_id)
    if entity_type == "annotation_target":
        linked_ids = select(db.AnnotationTargetLink.annotation_id).where(
            db.AnnotationTargetLink.annotation_target_id == target.id
        )
        entity_filter = or_(
            db.Annotation.annotation_target_id == target.id,
            db.Annotation.id.in_(linked_ids),
        )
    else:
        entity_filter = (db.Annotation.entity_type == entity_type) & (db.Annotation.entity_id == target.id)
    rows = session.scalars(
        select(db.Annotation)
        .where(entity_filter, db.Annotation.is_active.is_(True))
        .order_by(db.Annotation.created_at.desc())
    ).all()
    return [public_record(row) for row in rows]


@router.get("/annotations")
def list_annotations(query: str = "", include_archived: bool = False, session: Session = Depends(get_write_session)):
    stmt = select(db.Annotation)
    if not include_archived:
        stmt = stmt.where(db.Annotation.is_active.is_(True))
    if query:
        stmt = stmt.where(db.Annotation.subject.contains(query) | db.Annotation.body.contains(query))
    return [public_record(row) for row in session.scalars(stmt.order_by(db.Annotation.updated_at.desc()))]


@router.get("/annotations/{annotation_id}")
def get_annotation(annotation_id: int, session: Session = Depends(get_write_session)):
    record = session.get(db.Annotation, annotation_id)
    if record is None:
        raise APIError(404, "NOT_FOUND", f"Annotation '{annotation_id}' was not found.")
    return public_record(record)


@router.post("/annotations")
def create_global_annotation_route(
    payload: AnnotationCreate,
    session: Session = Depends(get_write_session),
    actor: ActorContext = Depends(require("annotation.write")),
):
    return create_global_annotation(session, actor, body(payload))


@router.get("/tag-assignments")
def list_tag_assignments(include_archived: bool = False, session: Session = Depends(get_write_session)):
    stmt = (
        select(db.EntityTag, db.Tag, db.AnnotationTarget)
        .join(db.Tag, db.Tag.id == db.EntityTag.tag_id)
        .outerjoin(db.AnnotationTarget, db.AnnotationTarget.id == db.EntityTag.annotation_target_id)
    )
    if not include_archived:
        stmt = stmt.where(db.EntityTag.removed_at.is_(None))
    results = []
    for assignment, tag, target in session.execute(stmt.order_by(db.EntityTag.assigned_at.desc())):
        results.append(
            {
                **public_record(assignment),
                "tag_name": tag.display_name,
                "color_key": tag.color_key,
                "target_id": target.target_uuid if target else assignment.entity_id,
                "target_type": target.target_type if target else assignment.entity_type,
                "target_label": target.target_label if target else None,
                "audit_id": target.audit_identifier if target else None,
                "machine_id": target.machine_identifier if target else None,
                "field_key": target.field_key if target else None,
                "field_label": target.field_label if target else None,
            }
        )
    return results


@router.post("/tag-assignments/archive")
def archive_tag_assignments_route(
    payload: TagAssignmentArchiveBatch,
    session: Session = Depends(get_write_session),
    actor: ActorContext = Depends(require("tag.assign")),
):
    return archive_tag_assignments(session, actor, payload.assignment_ids)


@router.post("/entities/{entity_type}/{entity_id}/annotations")
def create_annotation_route(
    entity_type: str,
    entity_id: str,
    payload: AnnotationCreate,
    session: Session = Depends(get_write_session),
    actor: ActorContext = Depends(require("annotation.write")),
):
    return create_annotation(session, actor, entity_type, entity_id, body(payload))


@router.patch("/annotations/{annotation_id}")
def update_annotation_route(
    annotation_id: int,
    payload: AnnotationPatch,
    session: Session = Depends(get_write_session),
    actor: ActorContext = Depends(require("annotation.write")),
):
    return update_annotation(session, actor, annotation_id, body(payload, exclude_unset=True))


@router.post("/annotations/{annotation_id}/archive")
def archive_annotation_route(
    annotation_id: int,
    payload: ExpectedVersion,
    session: Session = Depends(get_write_session),
    actor: ActorContext = Depends(require("annotation.write")),
):
    return update_annotation(session, actor, annotation_id, body(payload), archive=True)


@router.post("/annotations/{annotation_id}/targets/{target_id}")
def link_annotation_target_route(
    annotation_id: int,
    target_id: str,
    payload: ExpectedVersion,
    session: Session = Depends(get_write_session),
    actor: ActorContext = Depends(require("annotation.write")),
):
    return link_annotation_target(
        session,
        actor,
        annotation_id,
        target_id,
        payload.expected_row_version,
    )


@router.delete("/annotations/{annotation_id}/targets/{target_id}")
def unlink_annotation_target_route(
    annotation_id: int,
    target_id: str,
    payload: ExpectedVersion,
    session: Session = Depends(get_write_session),
    actor: ActorContext = Depends(require("annotation.write")),
):
    return unlink_annotation_target(
        session,
        actor,
        annotation_id,
        target_id,
        payload.expected_row_version,
    )


@router.post("/application-instances/register")
def register_instance_route(
    payload: ApplicationInstanceRegistration,
    session: Session = Depends(get_write_session),
    actor: ActorContext = Depends(require("instance.register")),
):
    return register_instance(session, actor, body(payload))


@router.post("/application-instances/heartbeat")
def heartbeat_instance_route(
    payload: ApplicationInstanceHeartbeat,
    session: Session = Depends(get_write_session),
    actor: ActorContext = Depends(require("instance.register")),
):
    return register_instance(session, actor, body(payload), heartbeat=True)
