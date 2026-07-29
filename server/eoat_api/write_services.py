from __future__ import annotations

import hashlib
import json
import mimetypes
import os
from collections.abc import Callable
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import inspect as sa_inspect
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.versioning.compatibility import EXPECTED_API_VERSION

from .contracts import FitCheckRequest
from .data_state import mark_data_changed
from .database import models as db
from .errors import APIError, conflict, not_found
from .release_provenance import ensure_application_release, release_id_for_instance
from .repositories import resolve_eoat_identity
from .security import ActorContext
from .services import AtlasService

CACHED_ENTITY_TYPES = {
    "eoat",
    "machine",
    "tool",
    "robot",
    "eoat_machine_compatibility",
    "eoat_tool_compatibility",
    "tool_machine_compatibility",
    "installation",
    "storage_assignment",
    "document",
    "photo",
    "tag",
    "entity_tag",
    "annotation",
    "audit",
    "maintenance",
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _json_value(value: Any) -> Any:
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def record_dict(record: Any) -> dict[str, Any]:
    return {column.key: _json_value(getattr(record, column.key)) for column in sa_inspect(record).mapper.columns}


def public_record(record: Any) -> dict[str, Any]:
    hidden = {"active_eoat_marker", "active_machine_marker", "active_assignment_key"}
    return {key: value for key, value in record_dict(record).items() if key not in hidden}


def lookup_id(
    session: Session, model: type, code: str | None, field_name: str, *, required: bool = False
) -> int | None:
    if code in (None, ""):
        if required:
            raise APIError(422, "LOOKUP_REQUIRED", f"{field_name} is required.", {"field": field_name})
        return None
    value = session.scalar(select(model.id).where(model.code == code, model.is_active.is_(True)))
    if value is None:
        raise APIError(422, "INVALID_LOOKUP", f"Unknown {field_name} value.", {"field": field_name, "value": code})
    return value


def check_version(record: Any, expected: int) -> None:
    if int(record.row_version) != int(expected):
        raise conflict(int(record.row_version))


def _history_type_id(session: Session, code: str) -> int:
    value = session.scalar(select(db.HistoryEventType.id).where(db.HistoryEventType.code == code))
    if value is None:
        raise APIError(503, "HISTORY_TYPE_MISSING", f"History event type '{code}' is not configured.")
    return value


def history_event_category(code: str) -> str:
    value = code.casefold()
    if any(token in value for token in ("installed", "removed", "moved_", "location_")):
        return "INSTALLATIONS"
    if "maintenance" in value or value == "pm_completed":
        return "MAINTENANCE"
    if "audit" in value:
        return "AUDITS"
    if "compatibility" in value or value in {"record_created", "record_edited"}:
        return "ENGINEERING_CHANGES"
    if "document" in value or "photo" in value:
        return "DOCUMENTS_AND_PHOTOS"
    if "tag" in value or "annotation" in value:
        return "TAGS_AND_ANNOTATIONS"
    if "archived" in value or "restored" in value:
        return "ARCHIVE_ACTIVITY"
    return "OTHER"


def history_relationship_metadata(session: Session, record: Any) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    machine_id = getattr(record, "machine_id", None)
    tool_id = getattr(record, "tool_id", None)
    robot_id = getattr(record, "robot_id", None)
    if machine_id:
        metadata["related_machine"] = session.scalar(
            select(db.Machine.machine_number).where(db.Machine.id == machine_id)
        )
    if tool_id:
        metadata["related_tool"] = session.scalar(
            select(db.Tool.business_identifier).where(db.Tool.id == tool_id)
        )
    if robot_id:
        metadata["related_robot"] = session.scalar(
            select(db.Robot.robot_number).where(db.Robot.id == robot_id)
        )
    return metadata


def add_history_event(
    session: Session,
    actor: ActorContext,
    *,
    entity_type: str,
    entity_id: int,
    history_code: str,
    summary: str,
    occurred_at: datetime | None = None,
    description: str | None = None,
    reason: str | None = None,
    notes: str | None = None,
    previous: dict[str, Any] | None = None,
    current: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    related_entity_type: str | None = None,
    related_entity_id: int | None = None,
    source_table: str | None = None,
    source_record_id: int | None = None,
) -> None:
    session.add(
        db.EntityHistoryEvent(
            event_uuid=str(uuid4()),
            entity_type=entity_type,
            entity_id=entity_id,
            event_type_id=_history_type_id(session, history_code),
            occurred_at=occurred_at or utcnow(),
            actor_user_id=actor.user_id,
            application_instance_id=actor.application_instance_id,
            application_release_id=release_id_for_instance(session, actor.application_instance_id),
            request_id=actor.request_id,
            event_category=history_event_category(history_code),
            summary=summary,
            description=description,
            details=description,
            reason=reason,
            notes=notes,
            previous_values_json=previous or None,
            new_values_json=current or None,
            metadata_json=metadata or None,
            related_entity_type=related_entity_type,
            related_entity_id=related_entity_id,
            source_table=source_table,
            source_record_id=source_record_id,
        )
    )


def audit_change(
    session: Session,
    actor: ActorContext,
    *,
    entity_type: str,
    entity_id: int,
    action: str,
    previous: dict[str, Any] | None,
    current: dict[str, Any] | None,
    row_version: int,
    reason: str | None = None,
    history_code: str | None = None,
    history_summary: str | None = None,
    history_entity_type: str | None = None,
    history_entity_id: int | None = None,
    history_description: str | None = None,
    history_notes: str | None = None,
    history_metadata: dict[str, Any] | None = None,
    related_entity_type: str | None = None,
    related_entity_id: int | None = None,
    source_table: str | None = None,
    source_record_id: int | None = None,
    change_feed_operation: str | None = None,
    fault_injector: Callable[[str], None] | None = None,
) -> None:
    previous = previous or {}
    current = current or {}
    changed = sorted(key for key in set(previous) | set(current) if previous.get(key) != current.get(key))
    session.add(
        db.ChangeAuditLog(
            event_uuid=str(uuid4()),
            request_id=actor.request_id,
            occurred_at=utcnow(),
            actor_user_id=actor.user_id,
            application_instance_id=actor.application_instance_id,
            application_release_id=release_id_for_instance(session, actor.application_instance_id),
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            previous_values_json=previous or None,
            new_values_json=current or None,
            changed_fields_json=changed,
            reason=reason,
            source="eoat_api",
            success=True,
            api_version=EXPECTED_API_VERSION,
            client_version=actor.client_version,
        )
    )
    if fault_injector:
        session.flush()
        fault_injector("audit_creation")
    if entity_type in CACHED_ENTITY_TYPES:
        # One request can create several audit/feed rows.  The data-state
        # transaction hook coalesces those into exactly one revision advance.
        mark_data_changed(session, actor)
        session.add(
            db.ChangeFeed(
                entity_type=entity_type,
                entity_id=entity_id,
                operation=change_feed_operation or action,
                entity_row_version=max(1, row_version),
                changed_by_user_id=actor.user_id,
                request_id=actor.request_id,
            )
        )
    if history_code:
        target_type = history_entity_type or entity_type
        target_id = history_entity_id or entity_id
        add_history_event(
            session,
            actor,
            entity_type=target_type,
            entity_id=target_id,
            history_code=history_code,
            summary=history_summary or action.replace("_", " ").title(),
            description=history_description,
            reason=reason,
            notes=history_notes,
            previous=previous,
            current=current,
            metadata=history_metadata,
            related_entity_type=related_entity_type,
            related_entity_id=related_entity_id,
            source_table=source_table,
            source_record_id=source_record_id,
        )
        if fault_injector:
            session.flush()
            fault_injector("history_creation")
        if target_type in CACHED_ENTITY_TYPES and (target_type, target_id) != (entity_type, entity_id):
            session.add(
                db.ChangeFeed(
                    entity_type=target_type,
                    entity_id=target_id,
                    operation="history",
                    entity_row_version=max(1, row_version),
                    changed_by_user_id=actor.user_id,
                    request_id=actor.request_id,
                )
            )


def _entity_by_identifier(session: Session, entity_type: str, identifier: str, *, lock: bool = False):
    if entity_type == "eoat":
        value = resolve_eoat_identity(session, identifier, lock=lock)
        if value is None:
            raise not_found(entity_type, identifier)
        return value
    mapping = {
        "machine": (db.Machine, db.Machine.machine_number),
        "tool": (db.Tool, db.Tool.business_identifier),
        "robot": (db.Robot, db.Robot.robot_number),
    }
    if entity_type not in mapping:
        raise APIError(422, "UNSUPPORTED_ENTITY_TYPE", f"Unsupported entity type '{entity_type}'.")
    model, column = mapping[entity_type]
    stmt = select(model).where(column == identifier)
    if lock:
        stmt = stmt.with_for_update()
    value = session.scalar(stmt)
    if value is None:
        raise not_found(entity_type, identifier)
    return value


def resolve_target(session: Session, entity_type: str, identifier: int | str):
    if entity_type == "annotation_target":
        value = session.scalar(
            select(db.AnnotationTarget).where(
                or_(db.AnnotationTarget.id == identifier, db.AnnotationTarget.target_uuid == str(identifier))
            )
        )
        if value is None:
            raise not_found("annotation target", identifier)
        return value
    if isinstance(identifier, int) or str(identifier).isdigit():
        model = {
            "eoat": db.EOAT,
            "machine": db.Machine,
            "tool": db.Tool,
            "robot": db.Robot,
            "audit": db.AuditRecord,
            "maintenance": db.MaintenanceEvent,
            "annotation": db.Annotation,
        }.get(entity_type)
        if model is not None:
            value = session.get(model, int(identifier))
            if value is not None:
                return value
    return _entity_by_identifier(session, entity_type, str(identifier))


ASSET_CONFIG = {
    "eoat": {
        "model": db.EOAT,
        "identifier": "business_identifier",
        "lookups": {
            "eoat_type": ("eoat_type_id", db.EOATType),
            "connection_type": ("connection_type_id", db.ConnectionType),
            "cleanroom_classification": ("cleanroom_classification_id", db.CleanroomClassification),
            "status": ("status_id", db.AssetStatus),
        },
    },
    "machine": {
        "model": db.Machine,
        "identifier": "machine_number",
        "lookups": {
            "cleanroom_classification": ("cleanroom_classification_id", db.CleanroomClassification),
            "status": ("status_id", db.AssetStatus),
        },
    },
    "tool": {
        "model": db.Tool,
        "identifier": "business_identifier",
        "lookups": {"status": ("status_id", db.AssetStatus)},
    },
    "robot": {
        "model": db.Robot,
        "identifier": "robot_number",
        "lookups": {"status": ("status_id", db.AssetStatus)},
    },
}


def _asset_values(session: Session, entity_type: str, payload: dict[str, Any], *, creating: bool) -> dict[str, Any]:
    config = ASSET_CONFIG[entity_type]
    values = dict(payload)
    values.pop("expected_row_version", None)
    values.pop("reason", None)
    if entity_type == "robot" and "robot_identifier" in values:
        values["robot_number"] = values.pop("robot_identifier")
    if entity_type == "eoat" and creating:
        # Identity is created once and is intentionally independent of the
        # selected machine, tool, or any later audit observation.
        values["physical_uuid"] = str(uuid4())
        values.setdefault("design_family_identifier", values.get("business_identifier"))
    for input_name, (column_name, lookup_model) in config["lookups"].items():
        if input_name in values:
            values[column_name] = lookup_id(session, lookup_model, values.pop(input_name), input_name)
    if entity_type in {"machine", "robot"}:
        plant_code = values.pop("plant_code", None)
        if creating:
            plant_id = session.scalar(
                select(db.Plant.id).where(db.Plant.plant_code == plant_code, db.Plant.is_active.is_(True))
            )
            if plant_id is None:
                raise APIError(422, "INVALID_PLANT", "Unknown or inactive plant_code.")
            values["plant_id"] = plant_id
        area_code = values.pop("area_code", None)
        if area_code is not None:
            plant_id = values.get("plant_id")
            if plant_id is None:
                raise APIError(422, "AREA_REQUIRES_PLANT", "area_code can only be changed with plant context.")
            area_id = session.scalar(
                select(db.Area.id).where(
                    db.Area.plant_id == plant_id, db.Area.area_code == area_code, db.Area.is_active.is_(True)
                )
            )
            if area_id is None:
                raise APIError(422, "INVALID_AREA", "Unknown or inactive area_code for the plant.")
            values["area_id"] = area_id
    return values


def create_asset(session: Session, actor: ActorContext, entity_type: str, payload: dict[str, Any]):
    config = ASSET_CONFIG[entity_type]
    values = _asset_values(session, entity_type, payload, creating=True)
    identifier = values["robot_number" if entity_type == "robot" else config["identifier"]]
    existing = session.scalar(
        select(config["model"].id).where(getattr(config["model"], config["identifier"]) == identifier)
    )
    if existing is not None:
        raise APIError(409, "DUPLICATE_IDENTIFIER", f"{entity_type.title()} identifier already exists.")
    record = config["model"](**values, created_by_user_id=actor.user_id, updated_by_user_id=actor.user_id)
    session.add(record)
    try:
        session.flush()
    except IntegrityError as exc:
        raise APIError(409, "DUPLICATE_OR_CONFLICTING_RECORD", f"The {entity_type} could not be created.") from exc
    current = record_dict(record)
    audit_change(
        session,
        actor,
        entity_type=entity_type,
        entity_id=record.id,
        action="create",
        previous=None,
        current=current,
        row_version=record.row_version,
        history_code="record_created",
        history_summary=f"{entity_type.title()} {identifier} created",
        source_table=config["model"].__tablename__,
        source_record_id=record.id,
    )
    return public_record(record)


def update_asset(session: Session, actor: ActorContext, entity_type: str, identifier: str, payload: dict[str, Any]):
    record = _entity_by_identifier(session, entity_type, identifier, lock=True)
    expected = payload.pop("expected_row_version")
    reason = payload.pop("reason", None)
    check_version(record, expected)
    previous = record_dict(record)
    values = _asset_values(session, entity_type, payload, creating=False)
    for key, value in values.items():
        setattr(record, key, value)
    record.row_version += 1
    record.updated_by_user_id = actor.user_id
    session.flush()
    current = record_dict(record)
    audit_change(
        session,
        actor,
        entity_type=entity_type,
        entity_id=record.id,
        action="update",
        previous=previous,
        current=current,
        row_version=record.row_version,
        reason=reason,
        history_code="record_edited",
        history_summary=f"{entity_type.title()} {identifier} edited",
        source_table=ASSET_CONFIG[entity_type]["model"].__tablename__,
        source_record_id=record.id,
    )
    return public_record(record)


def set_asset_archived(
    session: Session,
    actor: ActorContext,
    entity_type: str,
    identifier: str,
    expected: int,
    reason: str | None,
    archived: bool,
):
    record = _entity_by_identifier(session, entity_type, identifier, lock=True)
    check_version(record, expected)
    if archived and entity_type == "eoat":
        active_install = session.scalar(
            select(db.EOATInstallation.id).where(
                db.EOATInstallation.eoat_id == record.id, db.EOATInstallation.removed_at.is_(None)
            )
        )
        if active_install:
            raise APIError(409, "ACTIVE_RELATIONSHIP", "An installed EOAT cannot be archived.")
    previous = record_dict(record)
    record.is_active = not archived
    record.archived_at = utcnow() if archived else None
    record.archived_by_user_id = actor.user_id if archived else None
    record.row_version += 1
    record.updated_by_user_id = actor.user_id
    session.flush()
    action = "archive" if archived else "restore"
    audit_change(
        session,
        actor,
        entity_type=entity_type,
        entity_id=record.id,
        action=action,
        previous=previous,
        current=record_dict(record),
        row_version=record.row_version,
        reason=reason,
        history_code=f"record_{'archived' if archived else 'restored'}",
        history_summary=f"{entity_type.title()} {identifier} {action}d",
        source_table=ASSET_CONFIG[entity_type]["model"].__tablename__,
        source_record_id=record.id,
    )
    return public_record(record)


COMPATIBILITY_CONFIG = {
    "eoat-machine": (
        db.EOATMachineCompatibility,
        ("eoat_id", "eoat_identifier", "eoat"),
        ("machine_id", "machine_number", "machine"),
    ),
    "eoat-tool": (
        db.EOATToolCompatibility,
        ("eoat_id", "eoat_identifier", "eoat"),
        ("tool_id", "tool_identifier", "tool"),
    ),
    "tool-machine": (
        db.ToolMachineCompatibility,
        ("tool_id", "tool_identifier", "tool"),
        ("machine_id", "machine_number", "machine"),
    ),
}

COMPATIBILITY_WRITABLE_FIELDS = {
    "eoat-machine": frozenset(
        {"verified_at", "effective_from", "effective_to", "reason", "conditions", "notes", "connection_compatible", "payload_compatible", "reach_compatible", "cleanroom_compatible", "robot_interface_compatible", "utilities_compatible"}
    ),
    "eoat-tool": frozenset(
        {"verified_at", "effective_from", "effective_to", "reason", "conditions", "notes", "part_geometry_compatible", "number_of_parts_compatible", "vacuum_or_gripper_compatible", "sensor_compatible", "cycle_requirement_compatible"}
    ),
    "tool-machine": frozenset(
        {"verified_at", "effective_from", "effective_to", "reason", "conditions", "notes", "tonnage_compatible", "physical_size_compatible", "utilities_compatible", "process_compatible"}
    ),
}


def write_compatibility(
    session: Session,
    actor: ActorContext,
    relationship_type: str,
    payload: dict[str, Any],
    relationship_id: int | None = None,
):
    model, left, right = COMPATIBILITY_CONFIG[relationship_type]
    if relationship_id is None:
        left_record = _entity_by_identifier(session, left[2], payload.pop(left[1]))
        right_record = _entity_by_identifier(session, right[2], payload.pop(right[1]))
        values = {left[0]: left_record.id, right[0]: right_record.id}
        expected = payload.pop("expected_row_version", None)
        active = session.scalar(
            select(model).where(
                getattr(model, left[0]) == left_record.id,
                getattr(model, right[0]) == right_record.id,
                model.is_active.is_(True),
            )
        )
        if active is not None:
            raise APIError(409, "DUPLICATE_ACTIVE_RELATIONSHIP", "An active relationship already exists.")
        record = model(**values)
        previous = None
    else:
        record = session.scalar(select(model).where(model.id == relationship_id).with_for_update())
        if record is None:
            raise not_found("relationship", relationship_id)
        expected = payload.pop("expected_row_version", None)
        if expected is None:
            raise APIError(422, "EXPECTED_VERSION_REQUIRED", "expected_row_version is required.")
        check_version(record, expected)
        previous = record_dict(record)
    status = payload.pop("compatibility_status", None)
    if status is not None:
        record.compatibility_status_id = lookup_id(
            session, db.CompatibilityStatus, status, "compatibility_status", required=True
        )
    source = payload.pop("verification_source", None)
    if source is not None:
        record.verification_source_id = lookup_id(session, db.CompatibilitySource, source, "verification_source")
    attributes = payload.pop("attributes", {})
    allowed_attributes = COMPATIBILITY_WRITABLE_FIELDS[relationship_type]
    for key, value in {**payload, **attributes}.items():
        if key in {left[1], right[1]}:
            continue
        if key not in allowed_attributes:
            raise APIError(422, "INVALID_COMPATIBILITY_FIELD", f"Unsupported field '{key}'.")
        setattr(record, key, value)
    record.verified_by_user_id = actor.user_id
    record.updated_by_user_id = actor.user_id
    if relationship_id is None:
        record.created_by_user_id = actor.user_id
        session.add(record)
    else:
        record.row_version += 1
    session.flush()
    audit_change(
        session,
        actor,
        entity_type=model.__tablename__,
        entity_id=record.id,
        action="create" if relationship_id is None else "update",
        previous=previous,
        current=record_dict(record),
        row_version=record.row_version,
        history_code="compatibility_created" if relationship_id is None else "compatibility_updated",
        history_summary=f"{relationship_type} compatibility verified",
        history_entity_type="eoat" if getattr(record, "eoat_id", None) else None,
        history_entity_id=getattr(record, "eoat_id", None),
        history_metadata={**history_relationship_metadata(session, record), "relationship_type": relationship_type},
        source_table=model.__tablename__,
        source_record_id=record.id,
    )
    return public_record(record)


def archive_compatibility(
    session: Session,
    actor: ActorContext,
    relationship_type: str,
    relationship_id: int,
    expected: int,
    reason: str | None,
):
    model = COMPATIBILITY_CONFIG[relationship_type][0]
    record = session.scalar(select(model).where(model.id == relationship_id).with_for_update())
    if record is None:
        raise not_found("relationship", relationship_id)
    check_version(record, expected)
    previous = record_dict(record)
    record.is_active = False
    record.archived_at = utcnow()
    record.archived_by_user_id = actor.user_id
    record.updated_by_user_id = actor.user_id
    record.row_version += 1
    audit_change(
        session,
        actor,
        entity_type=model.__tablename__,
        entity_id=record.id,
        action="archive",
        previous=previous,
        current=record_dict(record),
        row_version=record.row_version,
        reason=reason,
        history_code="compatibility_archived" if getattr(record, "eoat_id", None) else None,
        history_summary=f"{relationship_type} compatibility archived",
        history_entity_type="eoat" if getattr(record, "eoat_id", None) else None,
        history_entity_id=getattr(record, "eoat_id", None),
        history_metadata={**history_relationship_metadata(session, record), "relationship_type": relationship_type},
        source_table=model.__tablename__,
        source_record_id=record.id,
    )
    return public_record(record)


def _close_active_locations(
    session: Session, actor: ActorContext, eoat_id: int, when: datetime, reason: str | None
) -> list[tuple[str, int]]:
    closed: list[tuple[str, int]] = []
    installation = session.scalar(
        select(db.EOATInstallation)
        .where(db.EOATInstallation.eoat_id == eoat_id, db.EOATInstallation.removed_at.is_(None))
        .with_for_update()
    )
    if installation:
        installation.removed_at = when
        installation.removed_by_user_id = actor.user_id
        installation.removal_reason = reason
        installation.row_version += 1
        closed.append(("installation", installation.id))
        audit_change(
            session,
            actor,
            entity_type="installation",
            entity_id=installation.id,
            action="close",
            previous=None,
            current=record_dict(installation),
            row_version=installation.row_version,
            reason=reason,
            history_code="removed",
            history_summary="EOAT removed from machine",
            history_entity_type="eoat",
            history_entity_id=eoat_id,
            history_metadata=history_relationship_metadata(session, installation),
            source_table="eoat_installations",
            source_record_id=installation.id,
        )
    storage = session.scalar(
        select(db.EOATStorageAssignment)
        .where(db.EOATStorageAssignment.eoat_id == eoat_id, db.EOATStorageAssignment.removed_from_storage_at.is_(None))
        .with_for_update()
    )
    if storage:
        storage.removed_from_storage_at = when
        storage.removed_by_user_id = actor.user_id
        closed.append(("storage_assignment", storage.id))
        audit_change(
            session,
            actor,
            entity_type="storage_assignment",
            entity_id=storage.id,
            action="close",
            previous=None,
            current=record_dict(storage),
            row_version=1,
            reason=reason,
        )
    return closed


def move_to_machine(
    session: Session,
    actor: ActorContext,
    eoat_identifier: str,
    payload: dict[str, Any],
    *,
    fault_injector: Callable[[str], None] | None = None,
):
    def asset_is_archived(value) -> bool:
        if not value.is_active:
            return True
        if value.status_id is None:
            return False
        status = session.scalar(select(db.AssetStatus.code).where(db.AssetStatus.id == value.status_id))
        return (status or "").strip().casefold() == "archived"

    eoat = _entity_by_identifier(session, "eoat", eoat_identifier, lock=True)
    check_version(eoat, payload["expected_row_version"])
    if asset_is_archived(eoat):
        raise APIError(409, "ARCHIVED_EOAT", "An archived EOAT cannot be installed.")
    machine_query = select(db.Machine).where(
        db.Machine.machine_number == payload["machine_number"], db.Machine.is_active.is_(True)
    )
    if payload.get("plant_code"):
        machine_query = machine_query.join(db.Plant, db.Plant.id == db.Machine.plant_id).where(
            db.Plant.plant_code == payload["plant_code"]
        )
    machines = list(session.scalars(machine_query.with_for_update()).all())
    if not machines:
        exists = session.scalar(select(db.Machine.id).where(db.Machine.machine_number == payload["machine_number"]))
        if exists:
            raise APIError(409, "ARCHIVED_MACHINE", "An archived machine cannot receive an EOAT.")
        raise not_found("machine", payload["machine_number"])
    if len(machines) != 1:
        raise APIError(409, "AMBIGUOUS_MACHINE", "plant_code is required when a machine number exists in multiple plants.")
    machine = machines[0]
    if asset_is_archived(machine):
        raise APIError(409, "ARCHIVED_MACHINE", "An archived machine cannot receive an EOAT.")
    tool = _entity_by_identifier(session, "tool", payload["tool_identifier"])
    if asset_is_archived(tool):
        raise APIError(409, "ARCHIVED_TOOL", "An archived tool cannot be installed.")
    robot = (
        _entity_by_identifier(session, "robot", payload["robot_identifier"])
        if payload.get("robot_identifier")
        else None
    )
    if robot is not None:
        if asset_is_archived(robot):
            raise APIError(409, "ARCHIVED_ROBOT", "An archived robot cannot be used for an installation.")
        assignment = session.scalar(
            select(db.MachineRobotAssignment.id).where(
                db.MachineRobotAssignment.machine_id == machine.id,
                db.MachineRobotAssignment.robot_id == robot.id,
                db.MachineRobotAssignment.removed_at.is_(None),
            )
        )
        if assignment is None:
            raise APIError(409, "ROBOT_MACHINE_MISMATCH", "The robot is not actively assigned to this machine.")
    fit_check = AtlasService(session).fit_check(
        FitCheckRequest(
            plant_code=payload.get("plant_code"),
            machine_number=machine.machine_number,
            tool_number=tool.business_identifier,
            eoat_identifier=eoat.business_identifier,
        )
    )
    override_reason = str(payload.get("override_reason") or "").strip()
    overridden = fit_check.overall_result != "COMPATIBLE"
    if overridden and not actor.permits("installation.override_compatibility"):
        raise APIError(403, "COMPATIBILITY_OVERRIDE_FORBIDDEN", "This identity cannot override compatibility.")
    if overridden and not override_reason:
        raise APIError(
            409,
            "INSTALLATION_COMPATIBILITY_BLOCKED",
            "Installation requires a COMPATIBLE Fit Check result.",
            {"fit_check": fit_check.model_dump(mode="json")},
        )
    when = payload.get("installed_at") or utcnow()
    closed_locations = _close_active_locations(session, actor, eoat.id, when, payload.get("reason"))
    installation = db.EOATInstallation(
        eoat_id=eoat.id,
        machine_id=machine.id,
        tool_id=tool.id,
        robot_id=robot.id if robot else None,
        installed_at=when,
        installed_by_user_id=actor.user_id,
        installation_reason=payload.get("reason") or override_reason,
        installation_notes=payload.get("notes"),
        application_instance_id=actor.application_instance_id,
        source="eoat_api",
    )
    session.add(installation)
    session.flush()
    if fault_injector:
        fault_injector("installation_creation")
    eoat.row_version += 1
    eoat.updated_by_user_id = actor.user_id
    session.flush()
    if fault_injector:
        fault_injector("eoat_version_update")
    current = record_dict(installation)
    application_release_id = release_id_for_instance(session, actor.application_instance_id)
    if fault_injector:
        fault_injector("release_provenance_lookup")
    audit_change(
        session,
        actor,
        entity_type="installation",
        entity_id=installation.id,
        action="installation_compatibility_override" if overridden else "create",
        previous=None,
        current=current,
        row_version=installation.row_version,
        reason=payload.get("reason"),
        history_code="installed",
        history_summary=f"{eoat.business_identifier} installed on {machine.machine_number}",
        related_entity_type="machine",
        related_entity_id=machine.id,
        history_entity_type="eoat",
        history_entity_id=eoat.id,
        history_notes=payload.get("notes"),
        history_metadata={
            "related_machine": machine.machine_number,
            "related_tool": tool.business_identifier,
            "related_robot": robot.robot_number if robot else None,
            "movement_kind": "moved_to_machine" if closed_locations else "installed",
            "compatibility_override": overridden,
            "override_reason": override_reason or None,
            "fit_check": fit_check.model_dump(mode="json"),
            "actor_identity": actor.identity,
            "request_id": actor.request_id,
            "application_instance_id": actor.application_instance_id,
            "application_release_id": application_release_id,
        },
        source_table="eoat_installations",
        source_record_id=installation.id,
        change_feed_operation="compatibility_override" if overridden else "create",
        fault_injector=fault_injector,
    )
    audit_change(
        session,
        actor,
        entity_type="eoat",
        entity_id=eoat.id,
        action="location_update",
        previous=None,
        current={"machine_id": machine.id},
        row_version=eoat.row_version,
        reason=payload.get("reason"),
    )
    return public_record(installation)


def close_installation(session: Session, actor: ActorContext, installation_id: int, payload: dict[str, Any]):
    record = session.scalar(
        select(db.EOATInstallation).where(db.EOATInstallation.id == installation_id).with_for_update()
    )
    if record is None:
        raise not_found("installation", installation_id)
    check_version(record, payload["expected_row_version"])
    if record.removed_at is not None:
        return public_record(record)
    when = payload.get("removed_at") or utcnow()
    if (
        when < record.installed_at.replace(tzinfo=when.tzinfo)
        if record.installed_at.tzinfo is None
        else when < record.installed_at
    ):
        raise APIError(422, "INVALID_REMOVAL_TIME", "Removal time cannot precede installation time.")
    previous = record_dict(record)
    record.removed_at = when
    record.removed_by_user_id = actor.user_id
    record.removal_reason = payload.get("reason")
    record.row_version += 1
    audit_change(
        session,
        actor,
        entity_type="installation",
        entity_id=record.id,
        action="close",
        previous=previous,
        current=record_dict(record),
        row_version=record.row_version,
        reason=payload.get("reason"),
        history_code="removed",
        history_summary="EOAT removed from machine",
        history_entity_type="eoat",
        history_entity_id=record.eoat_id,
        history_metadata=history_relationship_metadata(session, record),
        source_table="eoat_installations",
        source_record_id=record.id,
    )
    return public_record(record)


def move_to_storage(session: Session, actor: ActorContext, eoat_identifier: str, payload: dict[str, Any]):
    eoat = _entity_by_identifier(session, "eoat", eoat_identifier, lock=True)
    check_version(eoat, payload["expected_row_version"])
    location = session.scalar(
        select(db.StorageLocation)
        .where(
            db.StorageLocation.location_code == payload["storage_location_code"], db.StorageLocation.is_active.is_(True)
        )
        .with_for_update()
    )
    if location is None:
        raise not_found("storage location", payload["storage_location_code"])
    when = payload.get("stored_at") or utcnow()
    _close_active_locations(session, actor, eoat.id, when, payload.get("reason"))
    assignment = db.EOATStorageAssignment(
        eoat_id=eoat.id,
        storage_location_id=location.id,
        stored_at=when,
        stored_by_user_id=actor.user_id,
        reason=payload.get("reason"),
        notes=payload.get("notes"),
    )
    session.add(assignment)
    eoat.row_version += 1
    eoat.updated_by_user_id = actor.user_id
    session.flush()
    audit_change(
        session,
        actor,
        entity_type="storage_assignment",
        entity_id=assignment.id,
        action="create",
        previous=None,
        current=record_dict(assignment),
        row_version=1,
        reason=payload.get("reason"),
        history_code="moved_to_storage",
        history_summary=f"{eoat.business_identifier} moved to {location.location_code}",
        related_entity_type="storage_location",
        related_entity_id=location.id,
        history_entity_type="eoat",
        history_entity_id=eoat.id,
        history_notes=payload.get("notes"),
        history_metadata={"related_storage_location": location.location_code},
        source_table="eoat_storage_assignments",
        source_record_id=assignment.id,
    )
    audit_change(
        session,
        actor,
        entity_type="eoat",
        entity_id=eoat.id,
        action="location_update",
        previous=None,
        current={"storage_location_id": location.id},
        row_version=eoat.row_version,
        reason=payload.get("reason"),
    )
    return public_record(assignment)


def mark_location_unknown(
    session: Session, actor: ActorContext, eoat_identifier: str, expected: int, reason: str | None
):
    eoat = _entity_by_identifier(session, "eoat", eoat_identifier, lock=True)
    check_version(eoat, expected)
    closed = _close_active_locations(session, actor, eoat.id, utcnow(), reason)
    eoat.row_version += 1
    eoat.updated_by_user_id = actor.user_id
    audit_change(
        session,
        actor,
        entity_type="eoat",
        entity_id=eoat.id,
        action="location_unknown",
        previous={"closed": closed},
        current={"location": "unknown"},
        row_version=eoat.row_version,
        reason=reason,
        history_code="location_unknown",
        history_summary=f"{eoat.business_identifier} location marked unknown",
        source_table="eoats",
        source_record_id=eoat.id,
    )
    return {
        "eoat_identifier": eoat_identifier,
        "row_version": eoat.row_version,
        "location": "UNKNOWN",
        "closed_records": closed,
    }


def create_audit(session: Session, actor: ActorContext, payload: dict[str, Any]):
    if session.scalar(select(db.AuditRecord.id).where(db.AuditRecord.audit_identifier == payload["audit_identifier"])):
        raise APIError(409, "DUPLICATE_AUDIT", "The audit identifier already exists.")
    values: dict[str, Any] = {
        "audit_identifier": payload["audit_identifier"],
        "audit_date": payload.get("audit_date"),
        "details_json": payload.get("details") or {},
        "notes": payload.get("notes"),
        "performed_by_user_id": actor.user_id,
    }
    for input_name, column_name, entity_type in (
        ("eoat_identifier", "eoat_id", "eoat"),
        ("machine_number", "machine_id", "machine"),
        ("tool_identifier", "tool_id", "tool"),
        ("robot_identifier", "robot_id", "robot"),
    ):
        if payload.get(input_name):
            values[column_name] = _entity_by_identifier(session, entity_type, payload[input_name]).id
    if payload.get("status"):
        values["status_id"] = lookup_id(session, db.AssetStatus, payload["status"], "status")
    record = db.AuditRecord(**values, created_by_user_id=actor.user_id, updated_by_user_id=actor.user_id)
    session.add(record)
    session.flush()
    audit_change(
        session,
        actor,
        entity_type="audit",
        entity_id=record.id,
        action="create",
        previous=None,
        current=record_dict(record),
        row_version=record.row_version,
        history_code="audit_started",
        history_summary=f"Audit {record.audit_identifier} created",
        history_entity_type="eoat" if record.eoat_id else None,
        history_entity_id=record.eoat_id,
        history_notes=record.notes,
        history_metadata={"audit_id": record.audit_identifier, **history_relationship_metadata(session, record)},
        source_table="audit_records",
        source_record_id=record.id,
    )
    return public_record(record)


def update_audit(
    session: Session,
    actor: ActorContext,
    audit_id: int,
    payload: dict[str, Any],
    *,
    complete: bool = False,
    archive: bool = False,
):
    record = session.scalar(select(db.AuditRecord).where(db.AuditRecord.id == audit_id).with_for_update())
    if record is None:
        raise not_found("audit", audit_id)
    expected = payload.pop("expected_row_version")
    reason = payload.pop("reason", None)
    check_version(record, expected)
    previous = record_dict(record)
    if complete:
        record.status_id = lookup_id(session, db.AssetStatus, "completed", "status", required=True)
        record.audit_date = record.audit_date or utcnow()
    elif archive:
        record.is_active = False
        record.archived_at = utcnow()
        record.archived_by_user_id = actor.user_id
    else:
        if "status" in payload:
            record.status_id = lookup_id(session, db.AssetStatus, payload.pop("status"), "status")
        if "details" in payload:
            payload["details_json"] = payload.pop("details")
        for key, value in payload.items():
            setattr(record, key, value)
    record.row_version += 1
    record.updated_by_user_id = actor.user_id
    action = "complete" if complete else "archive" if archive else "update"
    audit_change(
        session,
        actor,
        entity_type="audit",
        entity_id=record.id,
        action=action,
        previous=previous,
        current=record_dict(record),
        row_version=record.row_version,
        reason=reason,
        history_code="audit_completed" if complete else "record_archived" if archive else "record_edited",
        history_summary=f"Audit {record.audit_identifier} {action}d",
        history_entity_type="eoat" if record.eoat_id else None,
        history_entity_id=record.eoat_id,
        history_notes=record.notes,
        history_metadata={"audit_id": record.audit_identifier, **history_relationship_metadata(session, record)},
        source_table="audit_records",
        source_record_id=record.id,
    )
    return public_record(record)


def create_maintenance(session: Session, actor: ActorContext, payload: dict[str, Any]):
    eoat = (
        _entity_by_identifier(session, "eoat", payload["eoat_identifier"]) if payload.get("eoat_identifier") else None
    )
    machine = (
        _entity_by_identifier(session, "machine", payload["machine_number"]) if payload.get("machine_number") else None
    )
    record = db.MaintenanceEvent(
        event_uuid=str(uuid4()),
        eoat_id=eoat.id if eoat else None,
        machine_id=machine.id if machine else None,
        event_type=payload["event_type"],
        status="OPEN",
        occurred_at=payload["occurred_at"],
        downtime_minutes=payload.get("downtime_minutes"),
        summary=payload["summary"],
        details_json=payload.get("details") or {},
        application_instance_id=actor.application_instance_id,
        created_by_user_id=actor.user_id,
        updated_by_user_id=actor.user_id,
    )
    session.add(record)
    session.flush()
    audit_change(
        session,
        actor,
        entity_type="maintenance",
        entity_id=record.id,
        action="create",
        previous=None,
        current=record_dict(record),
        row_version=record.row_version,
        history_code="maintenance_started",
        history_summary=record.summary,
        history_entity_type="eoat" if record.eoat_id else None,
        history_entity_id=record.eoat_id,
        history_description=str(record.details_json) if record.details_json else None,
        history_metadata={"maintenance_id": record.event_uuid, **history_relationship_metadata(session, record)},
        source_table="maintenance_events",
        source_record_id=record.id,
    )
    return public_record(record)


def update_maintenance(
    session: Session, actor: ActorContext, event_id: int, payload: dict[str, Any], *, complete: bool = False
):
    record = session.scalar(select(db.MaintenanceEvent).where(db.MaintenanceEvent.id == event_id).with_for_update())
    if record is None:
        raise not_found("maintenance event", event_id)
    expected = payload.pop("expected_row_version")
    reason = payload.pop("reason", None)
    check_version(record, expected)
    previous = record_dict(record)
    if record.status == "COMPLETED" and not complete:
        raise APIError(409, "COMPLETED_RECORD_IMMUTABLE", "Completed maintenance requires an amendment workflow.")
    if complete:
        record.status = "COMPLETED"
        record.completed_at = utcnow()
    else:
        if "details" in payload:
            payload["details_json"] = payload.pop("details")
        for key, value in payload.items():
            setattr(record, key, value)
    record.row_version += 1
    record.updated_by_user_id = actor.user_id
    audit_change(
        session,
        actor,
        entity_type="maintenance",
        entity_id=record.id,
        action="complete" if complete else "update",
        previous=previous,
        current=record_dict(record),
        row_version=record.row_version,
        reason=reason,
        history_code="maintenance_completed" if complete else "record_edited",
        history_summary=f"Maintenance {'completed' if complete else 'updated'}: {record.summary}",
        history_entity_type="eoat" if record.eoat_id else None,
        history_entity_id=record.eoat_id,
        history_description=str(record.details_json) if record.details_json else None,
        history_metadata={"maintenance_id": record.event_uuid, **history_relationship_metadata(session, record)},
        source_table="maintenance_events",
        source_record_id=record.id,
    )
    return public_record(record)


def _validate_document_path(storage_path: str) -> Path:
    path = Path(storage_path).expanduser()
    roots = [
        Path(value).expanduser() for value in os.getenv("EOAT_DOCUMENT_ROOTS", "").split(os.pathsep) if value.strip()
    ]
    if roots and not any(path.resolve().is_relative_to(root.resolve()) for root in roots):
        raise APIError(422, "UNCONTROLLED_DOCUMENT_PATH", "The document path is outside configured controlled roots.")
    if not path.exists() or not path.is_file():
        raise APIError(422, "DOCUMENT_FILE_UNAVAILABLE", "The document file must exist before metadata is committed.")
    return path


def _eoat_ids_for_document(session: Session, document_id: int) -> list[int]:
    return list(
        session.scalars(
            select(db.DocumentLink.entity_id).where(
                db.DocumentLink.document_id == document_id,
                db.DocumentLink.entity_type == "eoat",
            )
        ).all()
    )


def create_document(
    session: Session,
    actor: ActorContext,
    payload: dict[str, Any],
    *,
    emit_history: bool = True,
):
    path = _validate_document_path(payload["storage_path"])
    document_type = lookup_id(session, db.DocumentType, payload["document_type"], "document_type", required=True)
    record = db.Document(
        document_uuid=str(uuid4()),
        document_type_id=document_type,
        document_number=payload.get("document_number"),
        title=payload["title"],
        description=payload.get("description"),
        revision=payload.get("revision"),
        file_name=path.name,
        file_extension=path.suffix,
        mime_type=payload.get("mime_type") or mimetypes.guess_type(path.name)[0],
        storage_path=str(path),
        file_size_bytes=path.stat().st_size,
        checksum_sha256=payload.get("checksum_sha256"),
        created_by_user_id=actor.user_id,
        updated_by_user_id=actor.user_id,
    )
    session.add(record)
    session.flush()
    history_target_id = None
    history_target_type = None
    if payload.get("entity_type") and payload.get("entity_id"):
        target = resolve_target(session, payload["entity_type"], payload["entity_id"])
        history_target_type = payload["entity_type"]
        history_target_id = target.id
        session.add(
            db.DocumentLink(
                document_id=record.id,
                entity_type=payload["entity_type"],
                entity_id=target.id,
                relationship_type=payload.get("relationship_type", "attachment"),
                created_by_user_id=actor.user_id,
            )
        )
    audit_change(
        session,
        actor,
        entity_type="document",
        entity_id=record.id,
        action="create",
        previous=None,
        current=record_dict(record),
        row_version=record.row_version,
        history_code="document_added" if emit_history else None,
        history_summary=f"Document added: {record.title}",
        history_entity_type="eoat" if history_target_type == "eoat" else None,
        history_entity_id=history_target_id if history_target_type == "eoat" else None,
        history_metadata={"related_document": record.document_uuid, "file_name": record.file_name},
        source_table="documents",
        source_record_id=record.id,
    )
    return public_record(record)


def create_photo(session: Session, actor: ActorContext, payload: dict[str, Any]):
    photo_values = {key: payload.pop(key, None) for key in ("photo_view_type", "captured_at", "caption")}
    document = create_document(session, actor, payload, emit_history=False)
    photo = db.Photo(document_id=document["id"], captured_by_user_id=actor.user_id, **photo_values)
    session.add(photo)
    session.flush()
    audit_change(
        session,
        actor,
        entity_type="photo",
        entity_id=photo.id,
        action="create",
        previous=None,
        current=record_dict(photo),
        row_version=document["row_version"],
        history_code="photo_added",
        history_summary=f"Photo added: {document['title']}",
        history_entity_type="eoat" if payload.get("entity_type") == "eoat" else None,
        history_entity_id=int(payload["entity_id"]) if payload.get("entity_type") == "eoat" else None,
        history_metadata={"related_document": document["document_uuid"], "related_photo": photo.id},
        source_table="photos",
        source_record_id=photo.id,
    )
    return {"document": document, "photo": public_record(photo), "row_version": document["row_version"]}


def update_photo(
    session: Session, actor: ActorContext, photo_id: int, payload: dict[str, Any], *, archive: bool = False
):
    photo = session.scalar(select(db.Photo).where(db.Photo.id == photo_id).with_for_update())
    if photo is None:
        raise not_found("photo", photo_id)
    document = session.scalar(select(db.Document).where(db.Document.id == photo.document_id).with_for_update())
    expected = payload.pop("expected_row_version")
    reason = payload.pop("reason", None)
    check_version(document, expected)
    previous = {"document": record_dict(document), "photo": record_dict(photo)}
    if archive:
        document.is_active = False
        document.archived_at = utcnow()
        document.archived_by_user_id = actor.user_id
    else:
        for key, value in payload.items():
            if hasattr(photo, key):
                setattr(photo, key, value)
            elif hasattr(document, key):
                setattr(document, key, value)
    document.row_version += 1
    document.updated_by_user_id = actor.user_id
    current = {"document": record_dict(document), "photo": record_dict(photo)}
    eoat_ids = _eoat_ids_for_document(session, document.id)
    audit_change(
        session,
        actor,
        entity_type="photo",
        entity_id=photo.id,
        action="archive" if archive else "update",
        previous=previous,
        current=current,
        row_version=document.row_version,
        reason=reason,
        history_code="photo_archived" if archive else "photo_updated" if eoat_ids else None,
        history_summary=f"Photo {'archived' if archive else 'updated'}: {document.title}",
        history_entity_type="eoat" if eoat_ids else None,
        history_entity_id=eoat_ids[0] if eoat_ids else None,
        history_metadata={"related_document": document.document_uuid, "related_photo": photo.id},
        source_table="photos",
        source_record_id=photo.id,
    )
    return {"document": public_record(document), "photo": public_record(photo), "row_version": document.row_version}


def set_profile_photo(
    session: Session,
    actor: ActorContext,
    photo_id: int,
    expected_row_version: int,
    reason: str | None,
):
    photo = session.scalar(select(db.Photo).where(db.Photo.id == photo_id).with_for_update())
    if photo is None:
        raise not_found("photo", photo_id)
    document = session.scalar(select(db.Document).where(db.Document.id == photo.document_id).with_for_update())
    check_version(document, expected_row_version)
    link = session.scalar(
        select(db.DocumentLink).where(db.DocumentLink.document_id == document.id).order_by(db.DocumentLink.id)
    )
    if link is None:
        raise APIError(422, "PHOTO_ENTITY_LINK_REQUIRED", "A profile photo must be linked to an entity.")
    related_photo_ids = session.scalars(
        select(db.Photo.id)
        .join(db.Document, db.Document.id == db.Photo.document_id)
        .join(db.DocumentLink, db.DocumentLink.document_id == db.Document.id)
        .where(
            db.DocumentLink.entity_type == link.entity_type,
            db.DocumentLink.entity_id == link.entity_id,
            db.Document.is_active.is_(True),
        )
        .with_for_update()
    ).all()
    previous = {"document": record_dict(document), "photo": record_dict(photo)}
    if related_photo_ids:
        for related in session.scalars(select(db.Photo).where(db.Photo.id.in_(related_photo_ids))).all():
            related.is_profile_photo = related.id == photo.id
    photo.is_profile_photo = True
    document.row_version += 1
    document.updated_by_user_id = actor.user_id
    audit_change(
        session,
        actor,
        entity_type="photo",
        entity_id=photo.id,
        action="set_profile",
        previous=previous,
        current={"document": record_dict(document), "photo": record_dict(photo)},
        row_version=document.row_version,
        reason=reason,
        history_code="profile_photo_selected",
        history_summary=f"Profile photo selected for {link.entity_type} {link.entity_id}",
        related_entity_type=link.entity_type,
        related_entity_id=link.entity_id,
        history_entity_type="eoat" if link.entity_type == "eoat" else None,
        history_entity_id=link.entity_id if link.entity_type == "eoat" else None,
        history_metadata={"related_document": document.document_uuid, "related_photo": photo.id},
        source_table="photos",
        source_record_id=photo.id,
    )
    return {"document": public_record(document), "photo": public_record(photo), "row_version": document.row_version}


def update_document(
    session: Session, actor: ActorContext, document_id: int, payload: dict[str, Any], *, archive: bool = False
):
    record = session.scalar(select(db.Document).where(db.Document.id == document_id).with_for_update())
    if record is None:
        raise not_found("document", document_id)
    expected = payload.pop("expected_row_version")
    reason = payload.pop("reason", None)
    check_version(record, expected)
    previous = record_dict(record)
    if archive:
        record.is_active = False
        record.archived_at = utcnow()
        record.archived_by_user_id = actor.user_id
    else:
        if payload.get("storage_path"):
            path = _validate_document_path(payload["storage_path"])
            payload["file_name"] = path.name
            payload["file_extension"] = path.suffix
            payload["file_size_bytes"] = path.stat().st_size
        for key, value in payload.items():
            setattr(record, key, value)
    record.row_version += 1
    record.updated_by_user_id = actor.user_id
    eoat_ids = _eoat_ids_for_document(session, record.id)
    audit_change(
        session,
        actor,
        entity_type="document",
        entity_id=record.id,
        action="archive" if archive else "update",
        previous=previous,
        current=record_dict(record),
        row_version=record.row_version,
        reason=reason,
        history_code="document_archived" if archive else "document_updated" if eoat_ids else None,
        history_summary=f"Document {record.title} {'archived' if archive else 'updated'}",
        history_entity_type="eoat" if eoat_ids else None,
        history_entity_id=eoat_ids[0] if eoat_ids else None,
        history_metadata={"related_document": record.document_uuid, "file_name": record.file_name},
        source_table="documents",
        source_record_id=record.id,
    )
    return public_record(record)


def supersede_document(
    session: Session,
    actor: ActorContext,
    document_id: int,
    expected: int,
    replacement: dict[str, Any],
    reason: str | None,
):
    old = session.scalar(select(db.Document).where(db.Document.id == document_id).with_for_update())
    if old is None:
        raise not_found("document", document_id)
    check_version(old, expected)
    new = create_document(session, actor, replacement)
    old.superseded_by_document_id = new["id"]
    old.superseded_at = utcnow()
    old.row_version += 1
    old.updated_by_user_id = actor.user_id
    eoat_ids = _eoat_ids_for_document(session, old.id)
    audit_change(
        session,
        actor,
        entity_type="document",
        entity_id=old.id,
        action="supersede",
        previous=None,
        current=record_dict(old),
        row_version=old.row_version,
        reason=reason,
        history_code="document_superseded",
        history_summary=f"Document {old.title} superseded",
        history_entity_type="eoat" if eoat_ids else None,
        history_entity_id=eoat_ids[0] if eoat_ids else None,
        history_metadata={"related_document": old.document_uuid, "replacement_document_id": new["id"]},
        source_table="documents",
        source_record_id=old.id,
    )
    return {"superseded": public_record(old), "replacement": new}


def create_tag(session: Session, actor: ActorContext, payload: dict[str, Any]):
    if session.scalar(
        select(db.Tag.id).where(
            or_(db.Tag.tag_code == payload["tag_code"], db.Tag.display_name == payload["display_name"])
        )
    ):
        raise APIError(409, "DUPLICATE_TAG", "Tag code or name already exists.")
    record = db.Tag(**payload, created_by_user_id=actor.user_id, updated_by_user_id=actor.user_id)
    session.add(record)
    session.flush()
    audit_change(
        session,
        actor,
        entity_type="tag",
        entity_id=record.id,
        action="create",
        previous=None,
        current=record_dict(record),
        row_version=record.row_version,
        history_code="record_created",
        history_summary=f"Tag {record.display_name} created",
    )
    return public_record(record)


def update_tag(session: Session, actor: ActorContext, tag_id: int, payload: dict[str, Any], *, archive: bool = False):
    record = session.scalar(select(db.Tag).where(db.Tag.id == tag_id).with_for_update())
    if record is None:
        raise not_found("tag", tag_id)
    expected = payload.pop("expected_row_version")
    reason = payload.pop("reason", None)
    check_version(record, expected)
    previous = record_dict(record)
    if archive:
        record.is_active = False
        record.archived_at = utcnow()
        record.archived_by_user_id = actor.user_id
    else:
        for k, v in payload.items():
            setattr(record, k, v)
    record.row_version += 1
    record.updated_by_user_id = actor.user_id
    audit_change(
        session,
        actor,
        entity_type="tag",
        entity_id=record.id,
        action="archive" if archive else "update",
        previous=previous,
        current=record_dict(record),
        row_version=record.row_version,
        reason=reason,
    )
    return public_record(record)


def assign_tag(
    session: Session, actor: ActorContext, entity_type: str, entity_id: int | str, tag_id: int, comment: str | None
):
    target = resolve_target(session, entity_type, entity_id)
    tag = session.get(db.Tag, tag_id)
    if tag is None or not tag.is_active:
        raise not_found("active tag", tag_id)
    existing = session.scalar(
        select(db.EntityTag).where(
            db.EntityTag.tag_id == tag_id,
            db.EntityTag.entity_type == entity_type,
            db.EntityTag.entity_id == target.id,
            db.EntityTag.removed_at.is_(None),
        )
    )
    if existing:
        return public_record(existing)
    assignment = db.EntityTag(
        tag_id=tag_id,
        entity_type=entity_type,
        entity_id=target.id,
        annotation_target_id=target.id if entity_type == "annotation_target" else None,
        comment=comment,
        assigned_by_user_id=actor.user_id,
    )
    session.add(assignment)
    session.flush()
    audit_change(
        session,
        actor,
        entity_type="entity_tag",
        entity_id=assignment.id,
        action="assign",
        previous=None,
        current=record_dict(assignment),
        row_version=assignment.row_version,
        history_code="tag_assigned",
        history_summary=f"Tag {tag.display_name} assigned",
        related_entity_type=entity_type,
        related_entity_id=target.id,
        history_entity_type="eoat" if entity_type == "eoat" else None,
        history_entity_id=target.id if entity_type == "eoat" else None,
        history_notes=comment,
        history_metadata={"tag_id": tag.id, "tag_code": tag.tag_code, "tag_name": tag.display_name},
        source_table="entity_tags",
        source_record_id=assignment.id,
    )
    return public_record(assignment)


def remove_tag(
    session: Session, actor: ActorContext, entity_type: str, entity_id: int | str, tag_id: int, expected: int | None
):
    target = resolve_target(session, entity_type, entity_id)
    record = session.scalar(
        select(db.EntityTag)
        .where(
            db.EntityTag.tag_id == tag_id,
            db.EntityTag.entity_type == entity_type,
            db.EntityTag.entity_id == target.id,
            db.EntityTag.removed_at.is_(None),
        )
        .with_for_update()
    )
    if record is None:
        raise not_found("tag assignment", tag_id)
    if expected is not None:
        check_version(record, expected)
    previous = record_dict(record)
    record.removed_at = utcnow()
    record.removed_by_user_id = actor.user_id
    record.row_version += 1
    audit_change(
        session,
        actor,
        entity_type="entity_tag",
        entity_id=record.id,
        action="remove",
        previous=previous,
        current=record_dict(record),
        row_version=record.row_version,
        related_entity_type=entity_type,
        related_entity_id=target.id,
        history_code="tag_removed" if entity_type == "eoat" else None,
        history_summary="Tag removed",
        history_entity_type="eoat" if entity_type == "eoat" else None,
        history_entity_id=target.id if entity_type == "eoat" else None,
        history_metadata={"tag_id": tag_id},
        source_table="entity_tags",
        source_record_id=record.id,
    )
    return public_record(record)


def archive_tag_assignments(
    session: Session,
    actor: ActorContext,
    assignment_ids: list[int],
) -> dict[str, Any]:
    unique_ids = list(dict.fromkeys(assignment_ids))
    records = session.scalars(
        select(db.EntityTag).where(db.EntityTag.id.in_(unique_ids), db.EntityTag.removed_at.is_(None)).with_for_update()
    ).all()
    found = {record.id for record in records}
    missing = sorted(set(unique_ids) - found)
    if missing:
        raise APIError(
            409,
            "TAG_ASSIGNMENT_BATCH_CONFLICT",
            "One or more tag assignments are no longer active.",
            {"assignment_ids": missing},
        )
    for record in records:
        previous = record_dict(record)
        record.removed_at = utcnow()
        record.removed_by_user_id = actor.user_id
        record.row_version += 1
        audit_change(
            session,
            actor,
            entity_type="entity_tag",
            entity_id=record.id,
            action="remove",
            previous=previous,
            current=record_dict(record),
            row_version=record.row_version,
            related_entity_type=record.entity_type,
            related_entity_id=record.entity_id,
        )
    return {"archived_count": len(records), "assignment_ids": unique_ids}


def create_annotation(
    session: Session, actor: ActorContext, entity_type: str, entity_id: int | str, payload: dict[str, Any]
):
    target = resolve_target(session, entity_type, entity_id)
    record = db.Annotation(
        annotation_uuid=str(uuid4()),
        entity_type=entity_type,
        entity_id=target.id,
        annotation_target_id=target.id if entity_type == "annotation_target" else None,
        created_by_user_id=actor.user_id,
        updated_by_user_id=actor.user_id,
        **payload,
    )
    session.add(record)
    session.flush()
    if entity_type == "annotation_target":
        session.add(db.AnnotationTargetLink(annotation_id=record.id, annotation_target_id=target.id))
    audit_change(
        session,
        actor,
        entity_type="annotation",
        entity_id=record.id,
        action="create",
        previous=None,
        current=record_dict(record),
        row_version=record.row_version,
        history_code="annotation_added",
        history_summary=f"Annotation added: {record.subject}",
        related_entity_type=entity_type,
        related_entity_id=target.id,
        history_entity_type="eoat" if entity_type == "eoat" else None,
        history_entity_id=target.id if entity_type == "eoat" else None,
        history_description=record.body,
        history_metadata={"annotation_uuid": record.annotation_uuid, "annotation_type": record.annotation_type},
        source_table="annotations",
        source_record_id=record.id,
    )
    return public_record(record)


def link_annotation_target(
    session: Session,
    actor: ActorContext,
    annotation_id: int,
    target_identifier: str,
    expected_row_version: int,
) -> dict[str, Any]:
    annotation = session.scalar(select(db.Annotation).where(db.Annotation.id == annotation_id).with_for_update())
    if annotation is None:
        raise not_found("annotation", annotation_id)
    check_version(annotation, expected_row_version)
    target = resolve_target(session, "annotation_target", target_identifier)
    existing = session.scalar(
        select(db.AnnotationTargetLink).where(
            db.AnnotationTargetLink.annotation_id == annotation.id,
            db.AnnotationTargetLink.annotation_target_id == target.id,
        )
    )
    if existing is None:
        previous = record_dict(annotation)
        session.add(
            db.AnnotationTargetLink(
                annotation_id=annotation.id,
                annotation_target_id=target.id,
            )
        )
        annotation.row_version += 1
        annotation.updated_by_user_id = actor.user_id
        audit_change(
            session,
            actor,
            entity_type="annotation",
            entity_id=annotation.id,
            action="link_target",
            previous=previous,
            current=record_dict(annotation),
            row_version=annotation.row_version,
            related_entity_type="annotation_target",
            related_entity_id=target.id,
        )
    return public_record(annotation)


def unlink_annotation_target(
    session: Session,
    actor: ActorContext,
    annotation_id: int,
    target_identifier: str,
    expected_row_version: int,
) -> dict[str, Any]:
    annotation = session.scalar(select(db.Annotation).where(db.Annotation.id == annotation_id).with_for_update())
    if annotation is None:
        raise not_found("annotation", annotation_id)
    check_version(annotation, expected_row_version)
    target = resolve_target(session, "annotation_target", target_identifier)
    link = session.scalar(
        select(db.AnnotationTargetLink).where(
            db.AnnotationTargetLink.annotation_id == annotation.id,
            db.AnnotationTargetLink.annotation_target_id == target.id,
        )
    )
    if link is None:
        raise not_found("annotation target link", target_identifier)
    previous = record_dict(annotation)
    session.delete(link)
    annotation.row_version += 1
    annotation.updated_by_user_id = actor.user_id
    audit_change(
        session,
        actor,
        entity_type="annotation",
        entity_id=annotation.id,
        action="unlink_target",
        previous=previous,
        current=record_dict(annotation),
        row_version=annotation.row_version,
        related_entity_type="annotation_target",
        related_entity_id=target.id,
    )
    return public_record(annotation)


def create_global_annotation(session: Session, actor: ActorContext, payload: dict[str, Any]):
    record = db.Annotation(
        annotation_uuid=str(uuid4()), created_by_user_id=actor.user_id, updated_by_user_id=actor.user_id, **payload
    )
    session.add(record)
    session.flush()
    audit_change(
        session,
        actor,
        entity_type="annotation",
        entity_id=record.id,
        action="create",
        previous=None,
        current=record_dict(record),
        row_version=record.row_version,
        history_code="annotation_added",
        history_summary=f"Annotation added: {record.subject}",
    )
    return public_record(record)


def create_or_get_annotation_target(session: Session, actor: ActorContext, payload: dict[str, Any]):
    target_uuid = str(payload["target_uuid"])
    record = session.scalar(select(db.AnnotationTarget).where(db.AnnotationTarget.target_uuid == target_uuid))
    if record is not None:
        return public_record(record)
    record = db.AnnotationTarget(
        target_uuid=target_uuid,
        target_type=payload["target_type"],
        target_label=payload.get("target_label"),
        audit_identifier=payload.get("audit_identifier"),
        machine_identifier=payload.get("machine_identifier"),
        field_key=payload.get("field_key"),
        field_label=payload.get("field_label"),
        sheet_name=payload.get("sheet_name"),
        header_name=payload.get("header_name"),
        workbook_path=payload.get("workbook_path"),
        cached_cell_ref=payload.get("cached_cell_ref"),
        object_ref=payload.get("object_ref"),
        created_by_user_id=actor.user_id,
        updated_by_user_id=actor.user_id,
    )
    session.add(record)
    session.flush()
    audit_change(
        session,
        actor,
        entity_type="annotation_target",
        entity_id=record.id,
        action="create",
        previous=None,
        current=record_dict(record),
        row_version=record.row_version,
    )
    return public_record(record)


def update_annotation(
    session: Session, actor: ActorContext, annotation_id: int, payload: dict[str, Any], *, archive: bool = False
):
    record = session.scalar(select(db.Annotation).where(db.Annotation.id == annotation_id).with_for_update())
    if record is None:
        raise not_found("annotation", annotation_id)
    expected = payload.pop("expected_row_version")
    reason = payload.pop("reason", None)
    check_version(record, expected)
    previous = record_dict(record)
    if archive:
        record.is_active = False
        record.archived_at = utcnow()
        record.archived_by_user_id = actor.user_id
    else:
        for k, v in payload.items():
            setattr(record, k, v)
    record.row_version += 1
    record.updated_by_user_id = actor.user_id
    history_target_type = record.entity_type
    history_target_id = record.entity_id
    audit_change(
        session,
        actor,
        entity_type="annotation",
        entity_id=record.id,
        action="archive" if archive else "update",
        previous=previous,
        current=record_dict(record),
        row_version=record.row_version,
        reason=reason,
        history_code="annotation_archived" if archive else "annotation_updated" if history_target_type == "eoat" else None,
        history_summary=f"Annotation {'archived' if archive else 'updated'}: {record.subject}",
        history_entity_type="eoat" if history_target_type == "eoat" else None,
        history_entity_id=history_target_id if history_target_type == "eoat" else None,
        history_description=record.body,
        history_metadata={"annotation_uuid": record.annotation_uuid, "annotation_type": record.annotation_type},
        source_table="annotations",
        source_record_id=record.id,
    )
    return public_record(record)


def register_instance(session: Session, actor: ActorContext, payload: dict[str, Any], *, heartbeat: bool = False):
    record = session.scalar(
        select(db.ApplicationInstance)
        .where(db.ApplicationInstance.instance_uuid == payload["instance_uuid"])
        .with_for_update()
    )
    if heartbeat:
        if record is None:
            raise not_found("application instance", payload["instance_uuid"])
        record.last_seen_at = utcnow()
        if record.application_release_id:
            release = session.get(db.ApplicationRelease, record.application_release_id)
            if release is not None:
                release.last_seen_at = utcnow()
        return public_record(record)
    plant_id = area_id = None
    if payload.get("plant_code"):
        plant_id = session.scalar(select(db.Plant.id).where(db.Plant.plant_code == payload["plant_code"]))
        if plant_id is None:
            raise APIError(422, "INVALID_PLANT", "Unknown plant_code.")
    if payload.get("area_code"):
        area_id = session.scalar(
            select(db.Area.id).where(db.Area.plant_id == plant_id, db.Area.area_code == payload["area_code"])
        )
        if area_id is None:
            raise APIError(422, "INVALID_AREA", "Unknown area_code.")
    release = ensure_application_release(session, payload)
    instance_fields = {
        "instance_uuid",
        "computer_name",
        "application_version",
        "release_id",
        "build_id",
        "launcher_version",
        "operating_system",
    }
    values = {k: v for k, v in payload.items() if k in instance_fields} | {
        "plant_id": plant_id,
        "area_id": area_id,
        "application_release_id": release.id,
        "last_seen_at": utcnow(),
    }
    if record is None:
        record = db.ApplicationInstance(**values)
        session.add(record)
    else:
        for k, v in values.items():
            setattr(record, k, v)
    session.flush()
    return public_record(record)


def idempotent(
    session: Session,
    actor: ActorContext,
    operation: str,
    key: str | None,
    payload: dict[str, Any],
    execute: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    if not key:
        raise APIError(422, "IDEMPOTENCY_KEY_REQUIRED", "An Idempotency-Key header is required.")
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str, separators=(",", ":")).encode()
    ).hexdigest()
    existing = session.scalar(
        select(db.IdempotencyRecord)
        .where(
            db.IdempotencyRecord.actor_user_id == actor.user_id,
            db.IdempotencyRecord.operation == operation,
            db.IdempotencyRecord.idempotency_key == key,
        )
        .with_for_update()
    )
    if existing:
        if existing.request_hash != digest:
            raise APIError(
                409, "IDEMPOTENCY_KEY_REUSED", "This idempotency key was already used with a different request."
            )
        return dict(existing.response_json) | {"idempotent_replay": True}
    result = execute()
    session.add(
        db.IdempotencyRecord(
            actor_user_id=actor.user_id,
            operation=operation,
            idempotency_key=key,
            request_hash=digest,
            response_status=200,
            response_json=result,
            result_entity_type=operation.split(".")[0],
            result_entity_id=result.get("id"),
            request_id=actor.request_id,
        )
    )
    return result
