from __future__ import annotations

import os
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..corporate_auth import ADMINISTRATOR_GROUP_IDENTIFIER
from ..database import models as db
from ..errors import APIError, conflict, not_found
from ..security import ActorContext
from ..write_services import (
    ASSET_CONFIG,
    COMPATIBILITY_CONFIG,
    _asset_values,
    _entity_by_identifier,
    archive_compatibility,
    check_version,
    public_record,
    record_dict,
    set_asset_archived,
    update_asset,
    update_document,
    update_photo,
    write_compatibility,
)
from .diffing import material_diff
from .redaction import redact
from .service import AuditEventWriter
from .taxonomy import AuditAction, AuditSource

SAFE_DOCUMENT_FIELDS = {
    "document_number",
    "title",
    "description",
    "revision",
    "status_id",
    "effective_from",
}


def safe_record(record: Any) -> dict[str, Any]:
    value = public_record(record)
    # Document paths and checksums are operational internals, not Admin browser data.
    for key in ("storage_path", "checksum_sha256", "archived_by_user_id", "created_by_user_id", "updated_by_user_id"):
        value.pop(key, None)
    return value


def safe_view(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return safe_record(value)
    record = dict(value)
    for key in ("storage_path", "checksum_sha256", "archived_by_user_id", "created_by_user_id", "updated_by_user_id"):
        record.pop(key, None)
    return record


def asset_record(session: Session, entity_type: str, identifier: str) -> dict[str, Any]:
    return safe_record(_entity_by_identifier(session, entity_type, identifier))


def list_assets(session: Session, entity_type: str, search: str | None, include_archived: bool) -> list[dict[str, Any]]:
    config = ASSET_CONFIG[entity_type]
    model, identifier_column = config["model"], getattr(config["model"], config["identifier"])
    stmt = select(model)
    if not include_archived:
        stmt = stmt.where(model.is_active.is_(True))
    if search:
        needle = f"%{search.strip()}%"
        fields = [identifier_column]
        for name in ("display_name", "machine_name", "tool_number", "description"):
            field = getattr(model, name, None)
            if field is not None:
                fields.append(field)
        stmt = stmt.where(or_(*(field.like(needle) for field in fields)))
    rows = session.scalars(stmt.order_by(identifier_column).limit(100)).all()
    return [safe_record(row) for row in rows]


def list_documents(session: Session, search: str | None, include_archived: bool) -> list[dict[str, Any]]:
    stmt = select(db.Document)
    if not include_archived:
        stmt = stmt.where(db.Document.is_active.is_(True))
    if search:
        needle = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(
                db.Document.document_number.like(needle),
                db.Document.title.like(needle),
                db.Document.description.like(needle),
            )
        )
    return [safe_record(row) for row in session.scalars(stmt.order_by(db.Document.title).limit(100))]


def list_relationships(session: Session, relationship_type: str, include_archived: bool) -> list[dict[str, Any]]:
    model, left, right = COMPATIBILITY_CONFIG[relationship_type]
    stmt = select(model)
    if not include_archived:
        stmt = stmt.where(model.is_active.is_(True))
    rows = session.scalars(stmt.order_by(model.id.desc()).limit(100)).all()
    items = []
    for row in rows:
        left_record = session.get(ASSET_CONFIG[left[2]]["model"], getattr(row, left[0]))
        right_record = session.get(ASSET_CONFIG[right[2]]["model"], getattr(row, right[0]))
        status_record = session.get(db.CompatibilityStatus, row.compatibility_status_id)
        items.append(
            {
                "id": row.id,
                "row_version": row.row_version,
                "is_active": row.is_active,
                "left": getattr(left_record, ASSET_CONFIG[left[2]]["identifier"]) if left_record is not None else None,
                "right": getattr(right_record, ASSET_CONFIG[right[2]]["identifier"])
                if right_record is not None
                else None,
                "compatibility_status_id": row.compatibility_status_id,
                "compatibility_status": status_record.code if status_record is not None else None,
                "verification_source": getattr(row, "verification_source", None),
                "effective_from": getattr(row, "effective_from", None),
            }
        )
    return items


def document_record(session: Session, document_id: int) -> dict[str, Any]:
    record = session.get(db.Document, document_id)
    if record is None:
        raise not_found("document", document_id)
    return safe_record(record)


def update_document_governed(
    session: Session, actor: ActorContext, document_id: int, payload: dict[str, Any], *, archive: bool = False
) -> dict[str, Any]:
    record = update_document(
        session,
        actor,
        document_id,
        payload,
        archive=archive,
        audit_source=AuditSource.WEB,
        correlation_id=actor.request_id,
        governed_action=AuditAction.ARCHIVE if archive else AuditAction.METADATA_CHANGE,
    )
    return mutation_success(safe_view(record), audit_event_for_request(session, actor), actor)


def list_photos(session: Session, include_archived: bool) -> list[dict[str, Any]]:
    stmt = select(db.Photo, db.Document).join(db.Document, db.Document.id == db.Photo.document_id)
    if not include_archived:
        stmt = stmt.where(db.Document.is_active.is_(True))
    rows = session.execute(stmt.order_by(db.Photo.id.desc()).limit(100)).all()
    return [
        {"photo": safe_record(photo), "document": safe_record(document), "row_version": document.row_version}
        for photo, document in rows
    ]


def update_photo_governed(
    session: Session, actor: ActorContext, photo_id: int, payload: dict[str, Any], *, archive: bool = False
) -> dict[str, Any]:
    record = update_photo(
        session,
        actor,
        photo_id,
        payload,
        archive=archive,
        audit_source=AuditSource.WEB,
        correlation_id=actor.request_id,
        governed_action=AuditAction.PHOTO_ARCHIVE if archive else AuditAction.METADATA_CHANGE,
    )
    return mutation_success(
        {"document": safe_view(record["document"]), "photo": safe_view(record["photo"])},
        audit_event_for_request(session, actor),
        actor,
    )


def preview_asset_update(
    session: Session, entity_type: str, identifier: str, payload: dict[str, Any]
) -> dict[str, Any]:
    record = _entity_by_identifier(session, entity_type, identifier)
    expected = payload.pop("expected_row_version")
    payload.pop("reason", None)
    check_version(record, expected)
    previous = record_dict(record)
    values = _asset_values(session, entity_type, payload, creating=False)
    proposed = dict(previous)
    proposed.update(values)
    diff = material_diff(previous, proposed)
    return {
        "target": {"entity_type": entity_type, "identifier": identifier, "row_version": record.row_version},
        "changed_fields": diff.changed_fields,
        "before": redact(diff.before),
        "after": redact(diff.after),
        "requires_reason": False,
    }


def audit_event_for_request(
    session: Session, actor: ActorContext, *, correlation_id: str | None = None
) -> db.AuditEvent:
    event = session.scalar(
        select(db.AuditEvent)
        .where(
            db.AuditEvent.request_id == actor.request_id,
            db.AuditEvent.actor_user_id == actor.user_id,
            db.AuditEvent.correlation_id == (correlation_id or actor.request_id),
        )
        .order_by(db.AuditEvent.id.desc())
    )
    if event is None:
        raise APIError(500, "AUDIT_EVIDENCE_MISSING", "The governed mutation did not produce required audit evidence.")
    return event


def mutation_success(record: dict[str, Any], event: db.AuditEvent, actor: ActorContext) -> dict[str, Any]:
    return {
        "record": record,
        "audit_event_id": event.event_id,
        "correlation_id": event.correlation_id,
        "request_id": actor.request_id,
    }


def update_asset_governed(
    session: Session,
    actor: ActorContext,
    entity_type: str,
    identifier: str,
    payload: dict[str, Any],
    *,
    correction: bool = False,
) -> dict[str, Any]:
    if correction and not payload.get("reason"):
        raise APIError(422, "CORRECTION_REASON_REQUIRED", "A correction reason is required.", {"field": "reason"})
    record = update_asset(
        session,
        actor,
        entity_type,
        identifier,
        payload,
        audit_source=AuditSource.WEB,
        correlation_id=actor.request_id,
        governed_action=AuditAction.CORRECTION if correction else AuditAction.UPDATE,
    )
    return mutation_success(record, audit_event_for_request(session, actor), actor)


def lifecycle_asset_governed(
    session: Session,
    actor: ActorContext,
    entity_type: str,
    identifier: str,
    expected_row_version: int,
    reason: str,
    *,
    archived: bool,
) -> dict[str, Any]:
    record = set_asset_archived(
        session,
        actor,
        entity_type,
        identifier,
        expected_row_version,
        reason,
        archived,
        audit_source=AuditSource.WEB,
        correlation_id=actor.request_id,
    )
    return mutation_success(record, audit_event_for_request(session, actor), actor)


def link_relationship_governed(
    session: Session, actor: ActorContext, relationship_type: str, payload: dict[str, Any]
) -> dict[str, Any]:
    payload.pop("confirmation", None)
    payload.pop("reason", None)
    record = write_compatibility(
        session,
        actor,
        relationship_type,
        payload,
        audit_source=AuditSource.WEB,
        correlation_id=actor.request_id,
        governed_action=AuditAction.LINK,
    )
    return mutation_success(record, audit_event_for_request(session, actor), actor)


def unlink_relationship_governed(
    session: Session,
    actor: ActorContext,
    relationship_type: str,
    relationship_id: int,
    expected_row_version: int,
    reason: str,
) -> dict[str, Any]:
    record = archive_compatibility(
        session,
        actor,
        relationship_type,
        relationship_id,
        expected_row_version,
        reason,
        audit_source=AuditSource.WEB,
        correlation_id=actor.request_id,
    )
    return mutation_success(record, audit_event_for_request(session, actor), actor)


def relationship_unlink_preview(
    session: Session, relationship_type: str, relationship_id: int
) -> dict[str, Any]:
    """Resolve the relationship server-side before showing its destructive prompt."""

    model, left, right = COMPATIBILITY_CONFIG[relationship_type]
    record = session.get(model, relationship_id)
    if record is None or not record.is_active:
        raise not_found("active relationship", relationship_id)
    left_record = session.get(ASSET_CONFIG[left[2]]["model"], getattr(record, left[0]))
    right_record = session.get(ASSET_CONFIG[right[2]]["model"], getattr(record, right[0]))
    if left_record is None or right_record is None:
        raise not_found("relationship participant", relationship_id)

    def label(kind: str, value: Any) -> str:
        identifier = getattr(value, ASSET_CONFIG[kind]["identifier"])
        return f"{kind.upper() if kind == 'eoat' else kind.title()} {identifier}"

    left_label = label(left[2], left_record)
    right_label = label(right[2], right_record)
    status = session.get(db.CompatibilityStatus, record.compatibility_status_id)
    return {
        "relationship_type": relationship_type,
        "relationship_id": record.id,
        "row_version": record.row_version,
        "left": left_label,
        "right": right_label,
        "compatibility_status": status.code if status is not None else "Not recorded",
        "verification_source": getattr(record, "verification_source", None),
        "confirmation_phrase": f"Unlink {left_label} from {right_label}",
    }


def _expected_unlink_confirmation(session: Session, relationship_type: str, relationship_id: int) -> str:
    return str(relationship_unlink_preview(session, relationship_type, relationship_id)["confirmation_phrase"])


def _setting_metadata(record: db.SystemSetting) -> dict[str, Any]:
    """Authoritative browser presentation metadata; raw keys remain identities only."""

    if record.setting_key == "app.default_catalog_page_size":
        return {
            "label": "Default Library page size",
            "category": "Library & Search",
            "description": "How many Library results are shown by default when a user has not selected another page size.",
            "control_type": "select",
            "allowed_values": [25, 50, 100, 250],
            "editable": True,
            "environment_visibility": "all",
            "sensitivity": "normal",
        }
    if record.setting_key.startswith("phase3."):
        suffix = record.setting_key.rsplit(".", 1)[-1].replace("_", " ")
        return {
            "label": f"Phase 3 test setting ({suffix})",
            "category": "Test / Development",
            "description": "Acceptance-only configuration. It is not available in production Administrator Settings.",
            "control_type": "password" if record.is_sensitive else "text",
            "allowed_values": None,
            "editable": True,
            "environment_visibility": "non_production",
            "sensitivity": "secret" if record.is_sensitive else "test",
        }
    label = record.setting_key.replace("_", " ").replace(".", " · ").title()
    return {
        "label": label,
        "category": "Advanced",
        "description": record.description or "Server-declared Administrator setting.",
        "control_type": "password" if record.is_sensitive else record.value_type,
        "allowed_values": None,
        "editable": True,
        "environment_visibility": "all",
        "sensitivity": "secret" if record.is_sensitive else "normal",
    }


def _setting_visible(metadata: dict[str, Any]) -> bool:
    return metadata["environment_visibility"] != "non_production" or os.getenv("EOAT_API_ENVIRONMENT", "development") != "production"


def _setting_value(value: Any, value_type: str, sensitive: bool, metadata: dict[str, Any]) -> Any:
    if sensitive:
        if not isinstance(value, str) or not value:
            raise APIError(422, "INVALID_SECRET_SETTING", "A non-empty replacement secret is required.")
        return value
    if value_type == "boolean" and not isinstance(value, bool):
        raise APIError(422, "INVALID_SETTING_VALUE", "This setting requires a boolean value.")
    if value_type == "integer" and (not isinstance(value, int) or isinstance(value, bool)):
        raise APIError(422, "INVALID_SETTING_VALUE", "This setting requires an integer value.")
    if value_type == "string" and not isinstance(value, str):
        raise APIError(422, "INVALID_SETTING_VALUE", "This setting requires a string value.")
    allowed_values = metadata.get("allowed_values")
    if allowed_values and value not in allowed_values:
        raise APIError(422, "INVALID_SETTING_VALUE", "Choose one of the approved values for this setting.")
    return value


def setting_view(record: db.SystemSetting) -> dict[str, Any]:
    metadata = _setting_metadata(record)
    return {
        "key": record.setting_key,
        "value": None if record.is_sensitive else record.setting_value_json,
        "secret_configured": bool(record.setting_value_json) if record.is_sensitive else None,
        "value_type": record.value_type,
        "description": metadata["description"],
        "row_version": record.row_version,
        "restart_required": False,
        "presentation": metadata,
    }


def update_setting_governed(
    session: Session, actor: ActorContext, key: str, value: Any, expected_row_version: int, reason: str | None
) -> dict[str, Any]:
    record = session.scalar(select(db.SystemSetting).where(db.SystemSetting.setting_key == key).with_for_update())
    if record is None:
        raise not_found("setting", key)
    metadata = _setting_metadata(record)
    if not _setting_visible(metadata):
        raise APIError(404, "SETTING_NOT_AVAILABLE", "This setting is not available in this environment.")
    check_version(record, expected_row_version)
    next_value = _setting_value(value, record.value_type, record.is_sensitive, metadata)
    # A replacement of an already-configured sensitive setting must remain
    # reconstructable without serializing either the prior or supplied value.
    before = (
        {"configured": bool(record.setting_value_json), "replacement_recorded": False}
        if record.is_sensitive
        else {"value": record.setting_value_json}
    )
    record.setting_value_json = next_value
    record.row_version += 1
    record.updated_by_user_id = actor.user_id
    session.flush()
    after = (
        {"configured": bool(record.setting_value_json), "replacement_recorded": True}
        if record.is_sensitive
        else {"value": record.setting_value_json}
    )
    result = AuditEventWriter().write_change(
        session,
        actor,
        entity_type="Setting",
        entity_id=record.id,
        entity_display_id=record.setting_key,
        operation="admin.setting.update",
        previous=before,
        current=after,
        reason=reason,
        source=AuditSource.WEB,
        correlation_id=actor.request_id,
        action=AuditAction.SETTINGS_CHANGE,
    )
    return {
        "setting": setting_view(record),
        "audit_event_id": result.event_id,
        "correlation_id": actor.request_id,
        "request_id": actor.request_id,
    }


def group_policy_view(record: db.ExternalGroupRoleMapping) -> dict[str, Any]:
    """Return policy provenance without exposing directory credentials or membership."""

    return {
        "id": record.id,
        "corporate_group": record.external_group_identifier,
        "role_code": record.role_code,
        "provider": record.provider,
        "is_active": record.is_active,
        "status": "active" if record.is_active else "inactive",
        "is_protected_system_policy": _is_protected_group_policy(record),
        "row_version": record.row_version,
        "updated_at": record.updated_at,
    }


def setting_visible_view(record: db.SystemSetting) -> dict[str, Any] | None:
    metadata = _setting_metadata(record)
    return setting_view(record) if _setting_visible(metadata) else None


def _is_protected_group_policy(record: db.ExternalGroupRoleMapping) -> bool:
    return bool(record.is_system_policy) or (
        record.provider == "kerberos_form"
        and record.external_group_identifier == ADMINISTRATOR_GROUP_IDENTIFIER
        and record.role_code == "ADMINISTRATOR"
        and not record.explicit_deny
    )


def _ensure_policy_is_mutable(record: db.ExternalGroupRoleMapping) -> None:
    if _is_protected_group_policy(record):
        raise APIError(
            422,
            "SYSTEM_POLICY_PROTECTED",
            "The required Administrator recovery policy is protected and cannot be changed or removed.",
        )


def _active_role(session: Session, role_code: str) -> db.Role:
    role = session.scalar(select(db.Role).where(db.Role.role_code == role_code, db.Role.is_active.is_(True)))
    if role is None:
        raise APIError(422, "INVALID_ROLE", "The requested EOAT Atlas role is unavailable.")
    return role


def _normalize_group_identifier(value: str) -> str:
    identifier = value.strip()
    if len(identifier) < 3 or len(identifier) > 512 or any(character in identifier for character in "\r\n\x00"):
        raise APIError(422, "INVALID_GROUP_IDENTIFIER", "Provide the exact approved corporate group identifier.")
    return identifier


def _ensure_admin_recovery_path(
    session: Session, record: db.ExternalGroupRoleMapping, *, next_role: str, next_active: bool
) -> None:
    """Do not permit the editor to remove EOAT's final active Admin group path."""

    if record.role_code != "ADMINISTRATOR" or not record.is_active or (next_role == "ADMINISTRATOR" and next_active):
        return
    replacement = session.scalar(
        select(db.ExternalGroupRoleMapping.id).where(
            db.ExternalGroupRoleMapping.id != record.id,
            db.ExternalGroupRoleMapping.role_code == "ADMINISTRATOR",
            db.ExternalGroupRoleMapping.is_active.is_(True),
            db.ExternalGroupRoleMapping.explicit_deny.is_(False),
        )
    )
    if replacement is None:
        raise APIError(
            422,
            "ADMIN_RECOVERY_PATH_REQUIRED",
            "Keep another active Administrator group policy before deactivating or changing this policy.",
        )


def _revoke_sessions_for_group_policy(session: Session, group_identifier: str, *, reason: str) -> int:
    """Invalidate only existing corporate sessions that recorded this mapped group."""

    now = datetime.now(timezone.utc)
    rows = session.scalars(
        select(db.CorporateAuthenticationSession).where(
            db.CorporateAuthenticationSession.revoked_at.is_(None),
            db.CorporateAuthenticationSession.expires_at > now,
        )
    ).all()
    changed = 0
    for row in rows:
        if group_identifier in tuple(row.authorization_groups_json or ()):
            row.revoked_at = now
            row.revoke_reason = reason
            changed += 1
    return changed


def create_group_policy_governed(
    session: Session, actor: ActorContext, corporate_group: str, role_code: str, reason: str
) -> dict[str, Any]:
    identifier = _normalize_group_identifier(corporate_group)
    _active_role(session, role_code)
    duplicate = session.scalar(
        select(db.ExternalGroupRoleMapping.id).where(
            db.ExternalGroupRoleMapping.provider == "kerberos_form",
            db.ExternalGroupRoleMapping.external_group_identifier == identifier,
            db.ExternalGroupRoleMapping.role_code == role_code,
        )
    )
    if duplicate is not None:
        raise APIError(409, "GROUP_POLICY_DUPLICATE", "That corporate group already has this EOAT Atlas role policy.")
    now = datetime.now(timezone.utc)
    record = db.ExternalGroupRoleMapping(
        provider="kerberos_form",
        external_group_identifier=identifier,
        role_code=role_code,
        explicit_deny=False,
        is_active=True,
        is_system_policy=False,
        row_version=1,
        created_at=now,
        updated_at=now,
    )
    session.add(record)
    session.flush()
    result = AuditEventWriter().write_change(
        session,
        actor,
        entity_type="GroupPolicy",
        entity_id=record.id,
        entity_display_id=identifier,
        operation="admin.group-policy.create",
        previous={},
        current={"role_code": role_code, "is_active": True, "provider": record.provider},
        reason=reason,
        source=AuditSource.WEB,
        correlation_id=actor.request_id,
        action=AuditAction.GROUP_MAPPING_CHANGE,
    )
    return {
        "policy": group_policy_view(record),
        "audit_event_id": result.event_id,
        "correlation_id": actor.request_id,
        "request_id": actor.request_id,
    }


def update_group_policy_governed(
    session: Session,
    actor: ActorContext,
    mapping_id: int,
    role_code: str | None,
    is_active: bool | None,
    expected_row_version: int,
    reason: str,
) -> dict[str, Any]:
    record = session.scalar(
        select(db.ExternalGroupRoleMapping)
        .where(db.ExternalGroupRoleMapping.id == mapping_id, db.ExternalGroupRoleMapping.provider == "kerberos_form")
        .with_for_update()
    )
    if record is None:
        raise not_found("group policy", str(mapping_id))
    check_version(record, expected_row_version)
    _ensure_policy_is_mutable(record)
    next_role = role_code or record.role_code
    next_active = record.is_active if is_active is None else is_active
    _active_role(session, next_role)
    _ensure_admin_recovery_path(session, record, next_role=next_role, next_active=next_active)
    if next_role != record.role_code:
        duplicate = session.scalar(
            select(db.ExternalGroupRoleMapping.id).where(
                db.ExternalGroupRoleMapping.provider == record.provider,
                db.ExternalGroupRoleMapping.external_group_identifier == record.external_group_identifier,
                db.ExternalGroupRoleMapping.role_code == next_role,
                db.ExternalGroupRoleMapping.id != record.id,
            )
        )
        if duplicate is not None:
            raise APIError(
                409, "GROUP_POLICY_DUPLICATE", "That corporate group already has this EOAT Atlas role policy."
            )
    before = {"role_code": record.role_code, "is_active": record.is_active, "provider": record.provider}
    changed = record.role_code != next_role or record.is_active != next_active
    record.role_code = next_role
    record.is_active = next_active
    revoked_session_count = 0
    if changed:
        record.row_version += 1
        revoked_session_count = _revoke_sessions_for_group_policy(
            session, record.external_group_identifier, reason="group_policy_changed"
        )
    session.flush()
    after = {"role_code": record.role_code, "is_active": record.is_active, "provider": record.provider}
    result = AuditEventWriter().write_change(
        session,
        actor,
        entity_type="GroupPolicy",
        entity_id=record.id,
        entity_display_id=record.external_group_identifier,
        operation="admin.group-policy.update",
        previous=before,
        current=after,
        reason=reason,
        source=AuditSource.WEB,
        correlation_id=actor.request_id,
        action=AuditAction.GROUP_MAPPING_CHANGE,
    )
    return {
        "policy": group_policy_view(record),
        "audit_event_id": result.event_id,
        "correlation_id": actor.request_id,
        "request_id": actor.request_id,
        "revoked_session_count": revoked_session_count,
    }


def deactivate_group_policy_governed(
    session: Session, actor: ActorContext, mapping_id: int, expected_row_version: int, reason: str
) -> dict[str, Any]:
    record = session.scalar(
        select(db.ExternalGroupRoleMapping)
        .where(db.ExternalGroupRoleMapping.id == mapping_id, db.ExternalGroupRoleMapping.provider == "kerberos_form")
        .with_for_update()
    )
    if record is None:
        raise not_found("group policy", str(mapping_id))
    check_version(record, expected_row_version)
    _ensure_policy_is_mutable(record)
    _ensure_admin_recovery_path(session, record, next_role=record.role_code, next_active=False)
    if not record.is_active:
        raise APIError(409, "GROUP_POLICY_ALREADY_INACTIVE", "This group policy is already inactive.")
    before = {"role_code": record.role_code, "is_active": True, "provider": record.provider}
    record.is_active = False
    record.row_version += 1
    revoked_session_count = _revoke_sessions_for_group_policy(
        session, record.external_group_identifier, reason="group_policy_deactivated"
    )
    session.flush()
    result = AuditEventWriter().write_change(
        session, actor, entity_type="GroupPolicy", entity_id=record.id,
        entity_display_id=record.external_group_identifier, operation="admin.group-policy.deactivate",
        previous=before, current={"role_code": record.role_code, "is_active": False, "provider": record.provider},
        reason=reason, source=AuditSource.WEB, correlation_id=actor.request_id, action=AuditAction.GROUP_MAPPING_CHANGE,
    )
    return {"policy": group_policy_view(record), "audit_event_id": result.event_id,
            "correlation_id": actor.request_id, "request_id": actor.request_id,
            "revoked_session_count": revoked_session_count}


def update_mapping_governed(
    session: Session,
    actor: ActorContext,
    identity: str,
    role_code: str,
    expected_row_version: int,
    reason: str,
    environment: str,
) -> dict[str, Any]:
    mapping = session.scalar(
        select(db.DevelopmentIdentityMapping)
        .where(
            db.DevelopmentIdentityMapping.identity == identity,
            db.DevelopmentIdentityMapping.environment == environment,
            db.DevelopmentIdentityMapping.is_active.is_(True),
        )
        .with_for_update()
    )
    if mapping is None:
        raise not_found("development/test identity mapping", identity)
    check_version(mapping, expected_row_version)
    role = session.scalar(select(db.Role).where(db.Role.role_code == role_code, db.Role.is_active.is_(True)))
    if role is None:
        raise APIError(422, "INVALID_ROLE", "The requested application role is unavailable.")
    before = {"role_code": mapping.role_code, "environment": mapping.environment}
    mapping.role_code = role_code
    mapping.row_version += 1
    mapping.updated_by_user_id = actor.user_id
    user = session.scalar(select(db.User).where(db.User.external_identity == identity).with_for_update())
    if user is not None:
        for assignment in session.scalars(
            select(db.UserRole)
            .where(db.UserRole.user_id == user.id, db.UserRole.removed_at.is_(None))
            .with_for_update()
        ):
            assignment.removed_at = datetime.now(timezone.utc)
        session.add(db.UserRole(user_id=user.id, role_id=role.id, assigned_by_user_id=actor.user_id))
    result = AuditEventWriter().write_change(
        session,
        actor,
        entity_type="Identity",
        entity_id=mapping.id,
        entity_display_id=identity,
        operation="admin.access.test_mapping.update",
        previous=before,
        current={"role_code": role_code, "environment": mapping.environment},
        reason=reason,
        source=AuditSource.WEB,
        correlation_id=actor.request_id,
        action=AuditAction.ROLE_MAPPING_CHANGE,
    )
    return {
        "mapping": {
            "identity": identity,
            "environment": mapping.environment,
            "role_code": role_code,
            "row_version": mapping.row_version,
        },
        "audit_event_id": result.event_id,
        "correlation_id": actor.request_id,
        "request_id": actor.request_id,
    }


def bulk_status_preview(
    session: Session, identifiers: Iterable[str], status: str, expected_versions: dict[str, int]
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for identifier in identifiers:
        record = _entity_by_identifier(session, "eoat", identifier)
        expected = expected_versions[identifier]
        if record.row_version != expected:
            raise conflict(record.row_version)
        previous = record_dict(record)
        values = _asset_values(session, "eoat", {"status": status}, creating=False)
        proposed = dict(previous) | values
        diff = material_diff(previous, proposed)
        rows.append(
            {
                "identifier": identifier,
                "row_version": record.row_version,
                "changed_fields": diff.changed_fields,
                "before": diff.before,
                "after": diff.after,
            }
        )
    return {
        "operation": "admin.eoat.bulk-status",
        "status": status,
        "count": len(rows),
        "records": rows,
        "atomic": True,
    }


def bulk_status_commit(
    session: Session,
    actor: ActorContext,
    identifiers: Iterable[str],
    status: str,
    expected_versions: dict[str, int],
    reason: str,
) -> dict[str, Any]:
    preview = bulk_status_preview(session, identifiers, status, expected_versions)
    correlation_id = actor.request_id
    changed = []
    for identifier in identifiers:
        result = update_asset(
            session,
            actor,
            "eoat",
            identifier,
            {"status": status, "expected_row_version": expected_versions[identifier], "reason": reason},
            audit_source=AuditSource.WEB,
            correlation_id=correlation_id,
            governed_action=AuditAction.STATUS_CHANGE,
        )
        changed.append({"identifier": identifier, "row_version": result["row_version"]})
    parent = AuditEventWriter().write_change(
        session,
        actor,
        entity_type="BulkOperation",
        entity_id=correlation_id,
        entity_display_id="EOAT status update",
        operation="admin.eoat.bulk-status.commit",
        previous={"count": 0, "identifiers": list(identifiers)},
        current={"count": len(changed), "status": status},
        reason=reason,
        source=AuditSource.WEB,
        correlation_id=correlation_id,
        action=AuditAction.BULK_OPERATION,
        metadata={"atomic": True, "preview_count": preview["count"], "failed_count": 0},
    )
    return {
        "operation": preview["operation"],
        "status": "SUCCESS",
        "atomic": True,
        "affected_count": len(changed),
        "failed_count": 0,
        "records": changed,
        "audit_event_id": parent.event_id,
        "correlation_id": correlation_id,
        "request_id": actor.request_id,
    }
