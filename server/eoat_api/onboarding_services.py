"""Transactional orchestration for the EOAT onboarding candidate.

This module deliberately composes the normal write services.  It never makes a
draft discoverable as an EOAT, and it does not create a second media, history,
compatibility, authorization, or location system.
"""

from __future__ import annotations

import base64
import binascii
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import models as db
from .errors import APIError, conflict, not_found
from .security import ActorContext
from .write_contracts import CompatibilityWrite, EOATCreate
from .write_services import (
    _validate_document_path,
    audit_change,
    create_asset,
    create_document,
    create_photo,
    move_to_machine,
    move_to_storage,
    record_dict,
    set_profile_photo,
    utcnow,
    write_compatibility,
)

ENGINEERING_FIELDS = frozenset(
    {
        "cylinders_present",
        "cylinder_count",
        "cylinder_type",
        "cylinder_model",
        "gripper_type",
        "gripper_model",
        "gripper_size",
        "vacuum_cup_type",
        "vacuum_cup_size",
        "vacuum_cup_model",
        "vacuum_generation",
        "vacuum_circuits",
        "pressure_circuits",
        "interchangeable_circuits",
        "external_circuits",
        "pneumatic_connection",
        "pneumatic_notes",
        "electrical_present",
        "electrical_connection",
        "electrical_pinout_reference",
        "sensor_types",
        "sensor_models",
    }
)


def onboarding_enabled() -> bool:
    return os.getenv("EOAT_ONBOARDING_ENABLED", "false").strip().casefold() in {"1", "true", "yes", "on"}


def require_onboarding_enabled() -> None:
    if not onboarding_enabled():
        raise APIError(403, "ONBOARDING_FEATURE_DISABLED", "EOAT onboarding is not enabled in this environment.")


def _identifier(value: str | None) -> str | None:
    normalized = (value or "").strip().upper()
    if not normalized:
        return None
    if len(normalized) > 64:
        raise APIError(422, "IDENTIFIER_INVALID", "The proposed EOAT identifier is too long.")
    return normalized


def _draft(session: Session, draft_uuid: str, *, lock: bool = False) -> db.EOATOnboardingDraft:
    stmt = select(db.EOATOnboardingDraft).where(db.EOATOnboardingDraft.draft_uuid == draft_uuid)
    if lock:
        stmt = stmt.with_for_update()
    result = session.scalar(stmt)
    if result is None:
        raise not_found("onboarding draft", draft_uuid)
    return result


def _check_draft_version(draft: db.EOATOnboardingDraft, expected: int) -> None:
    if int(draft.row_version) != int(expected):
        raise conflict(int(draft.row_version))
    if draft.lifecycle_state != "DRAFT":
        raise APIError(409, "DRAFT_NOT_EDITABLE", "Only an active onboarding draft can be changed.")


def _assert_draft_editor(actor: ActorContext, draft: db.EOATOnboardingDraft) -> None:
    """Draft preparation is owner-scoped unless a reviewer is explicitly granted."""
    if draft.created_by_user_id != actor.user_id and not actor.permits("onboarding.draft.review"):
        raise APIError(403, "PERMISSION_DENIED", "The authenticated identity cannot edit this onboarding draft.")


def _draft_summary(draft: db.EOATOnboardingDraft) -> dict[str, Any]:
    return {
        "draft_uuid": draft.draft_uuid,
        "proposed_identifier": draft.proposed_identifier,
        "plant_code": draft.plant_code,
        "area_code": draft.area_code,
        "lifecycle_state": draft.lifecycle_state,
        "completion_state": draft.completion_state,
        "payload": draft.payload_json,
        "row_version": draft.row_version,
        "created_at": draft.created_at,
        "updated_at": draft.updated_at,
        "finalized_eoat_id": draft.finalized_eoat_id,
        "finalized_at": draft.finalized_at,
    }


def _reserve_identifier(
    session: Session, actor: ActorContext, draft: db.EOATOnboardingDraft, value: str | None
) -> None:
    normalized = _identifier(value)
    if not normalized:
        return
    existing_eoat = session.scalar(select(db.EOAT.id).where(db.EOAT.business_identifier == normalized))
    if existing_eoat is not None:
        raise APIError(409, "DUPLICATE_IDENTIFIER", "An EOAT already uses this identifier.")
    reservation = session.scalar(
        select(db.EOATIdentifierReservation)
        .where(db.EOATIdentifierReservation.normalized_identifier == normalized)
        .with_for_update()
    )
    if reservation is None:
        session.add(
            db.EOATIdentifierReservation(
                normalized_identifier=normalized, draft_id=draft.id, reserved_by_user_id=actor.user_id
            )
        )
        return
    if reservation.draft_id != draft.id and reservation.released_at is None:
        raise APIError(409, "IDENTIFIER_RESERVED", "Another active onboarding draft has reserved this identifier.")
    reservation.draft_id = draft.id
    reservation.reserved_by_user_id = actor.user_id
    reservation.released_at = None


def _release_other_reservations(session: Session, draft: db.EOATOnboardingDraft, keep: str | None = None) -> None:
    for row in session.scalars(
        select(db.EOATIdentifierReservation).where(db.EOATIdentifierReservation.draft_id == draft.id)
    ).all():
        if row.normalized_identifier != keep and row.released_at is None:
            row.released_at = utcnow()


def _completion(payload: dict[str, Any]) -> str:
    identity = payload.get("identity") if isinstance(payload.get("identity"), dict) else {}
    if not identity.get("business_identifier") or not identity.get("eoat_type"):
        return "INCOMPLETE"
    return "READY_FOR_REVIEW"


def create_draft(session: Session, actor: ActorContext, payload: dict[str, Any]) -> dict[str, Any]:
    proposed = _identifier(
        payload.get("proposed_identifier")
        or (payload.get("payload") or {}).get("identity", {}).get("business_identifier")
    )
    draft = db.EOATOnboardingDraft(
        draft_uuid=str(uuid4()),
        proposed_identifier=proposed,
        plant_code=payload.get("plant_code"),
        area_code=payload.get("area_code"),
        payload_json=payload.get("payload") or {},
        completion_state=_completion(payload.get("payload") or {}),
        created_by_user_id=actor.user_id,
        updated_by_user_id=actor.user_id,
    )
    session.add(draft)
    session.flush()
    _reserve_identifier(session, actor, draft, proposed)
    audit_change(
        session,
        actor,
        entity_type="onboarding_draft",
        entity_id=draft.id,
        action="create",
        previous=None,
        current=record_dict(draft),
        row_version=draft.row_version,
        history_code=None,
        source_table=draft.__tablename__,
        source_record_id=draft.id,
    )
    return _draft_summary(draft)


def update_draft(session: Session, actor: ActorContext, draft_uuid: str, payload: dict[str, Any]) -> dict[str, Any]:
    draft = _draft(session, draft_uuid, lock=True)
    _assert_draft_editor(actor, draft)
    _check_draft_version(draft, payload["expected_row_version"])
    before = record_dict(draft)
    state = payload.get("payload") or {}
    proposed = _identifier(
        payload.get("proposed_identifier")
        or state.get("identity", {}).get("business_identifier")
        or draft.proposed_identifier
    )
    _reserve_identifier(session, actor, draft, proposed)
    _release_other_reservations(session, draft, proposed)
    draft.proposed_identifier, draft.plant_code, draft.area_code, draft.payload_json = (
        proposed,
        payload.get("plant_code"),
        payload.get("area_code"),
        state,
    )
    draft.completion_state, draft.row_version, draft.updated_by_user_id = (
        _completion(state),
        draft.row_version + 1,
        actor.user_id,
    )
    session.flush()
    audit_change(
        session,
        actor,
        entity_type="onboarding_draft",
        entity_id=draft.id,
        action="update",
        previous=before,
        current=record_dict(draft),
        row_version=draft.row_version,
        source_table=draft.__tablename__,
        source_record_id=draft.id,
    )
    return _draft_summary(draft)


def discard_draft(
    session: Session, actor: ActorContext, draft_uuid: str, expected: int, reason: str | None
) -> dict[str, Any]:
    draft = _draft(session, draft_uuid, lock=True)
    _assert_draft_editor(actor, draft)
    _check_draft_version(draft, expected)
    before = record_dict(draft)
    draft.lifecycle_state, draft.discarded_at, draft.discard_reason = "DISCARDED", utcnow(), reason
    draft.row_version += 1
    draft.updated_by_user_id = actor.user_id
    _release_other_reservations(session, draft)
    for media in session.scalars(
        select(db.EOATOnboardingStagedMedia).where(
            db.EOATOnboardingStagedMedia.draft_id == draft.id, db.EOATOnboardingStagedMedia.is_active.is_(True)
        )
    ).all():
        media.is_active = False
        media.archived_at = utcnow()
        media.archived_by_user_id = actor.user_id
    audit_change(
        session,
        actor,
        entity_type="onboarding_draft",
        entity_id=draft.id,
        action="discard",
        previous=before,
        current=record_dict(draft),
        row_version=draft.row_version,
        reason=reason,
        source_table=draft.__tablename__,
        source_record_id=draft.id,
    )
    return _draft_summary(draft)


def list_drafts(session: Session, actor: ActorContext) -> list[dict[str, Any]]:
    rows = session.scalars(
        select(db.EOATOnboardingDraft)
        .where(db.EOATOnboardingDraft.lifecycle_state == "DRAFT")
        .order_by(db.EOATOnboardingDraft.updated_at.desc())
    ).all()
    if actor.permits("onboarding.draft.review"):
        return [_draft_summary(row) for row in rows]
    return [_draft_summary(row) for row in rows if row.created_by_user_id == actor.user_id]


def stage_media(session: Session, actor: ActorContext, draft_uuid: str, payload: dict[str, Any]) -> dict[str, Any]:
    draft = _draft(session, draft_uuid, lock=True)
    _assert_draft_editor(actor, draft)
    _check_draft_version(draft, payload.pop("expected_row_version"))
    path = _validate_document_path(payload["storage_path"])
    if path.name != Path(payload["file_name"]).name:
        raise APIError(422, "STAGED_MEDIA_NAME_MISMATCH", "The staged file name must match the controlled file path.")
    media = db.EOATOnboardingStagedMedia(
        draft_id=draft.id, **payload, created_by_user_id=actor.user_id, updated_by_user_id=actor.user_id
    )
    session.add(media)
    draft.row_version += 1
    draft.updated_by_user_id = actor.user_id
    session.flush()
    audit_change(
        session,
        actor,
        entity_type="onboarding_draft",
        entity_id=draft.id,
        action="stage_media",
        previous=None,
        current={"draft": record_dict(draft), "media": record_dict(media)},
        row_version=draft.row_version,
        source_table=media.__tablename__,
        source_record_id=media.id,
    )
    return {"id": media.id, "row_version": draft.row_version}


def stage_uploaded_media(
    session: Session, actor: ActorContext, draft_uuid: str, payload: dict[str, Any]
) -> dict[str, Any]:
    """Persist upload bytes only in the configured draft staging root.

    The finalization service still re-validates the resulting path against the
    ordinary controlled document roots before it creates normal media metadata.
    """
    encoded = payload.pop("content_base64")
    try:
        content = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise APIError(422, "STAGED_MEDIA_INVALID", "The uploaded media is not valid base64.") from exc
    if len(content) > 25 * 1024 * 1024:
        raise APIError(422, "STAGED_MEDIA_TOO_LARGE", "Staged media must not exceed 25 MB.")
    root_value = os.getenv("EOAT_ONBOARDING_STAGING_ROOT", "").strip()
    if not root_value:
        raise APIError(
            503, "ONBOARDING_STAGING_UNAVAILABLE", "The controlled onboarding staging root is not configured."
        )
    root = Path(root_value).resolve()
    if not root.is_dir():
        raise APIError(503, "ONBOARDING_STAGING_UNAVAILABLE", "The controlled onboarding staging root is unavailable.")
    safe_name = Path(str(payload["file_name"])).name
    if safe_name in {"", ".", ".."}:
        raise APIError(422, "STAGED_MEDIA_NAME_INVALID", "The uploaded file name is invalid.")
    destination = root / f"{uuid4()}_{safe_name}"
    destination.write_bytes(content)
    try:
        return stage_media(
            session, actor, draft_uuid, {**payload, "file_name": safe_name, "storage_path": str(destination)}
        )
    except Exception:
        destination.unlink(missing_ok=True)
        raise


def remove_staged_media(
    session: Session, actor: ActorContext, draft_uuid: str, media_id: int, expected: int
) -> dict[str, Any]:
    draft = _draft(session, draft_uuid, lock=True)
    _assert_draft_editor(actor, draft)
    _check_draft_version(draft, expected)
    media = session.scalar(
        select(db.EOATOnboardingStagedMedia)
        .where(db.EOATOnboardingStagedMedia.id == media_id, db.EOATOnboardingStagedMedia.draft_id == draft.id)
        .with_for_update()
    )
    if media is None or not media.is_active:
        raise not_found("staged onboarding media", media_id)
    previous = record_dict(media)
    media.is_active, media.archived_at, media.archived_by_user_id = False, utcnow(), actor.user_id
    media.row_version += 1
    media.updated_by_user_id = actor.user_id
    draft.row_version += 1
    draft.updated_by_user_id = actor.user_id
    audit_change(
        session,
        actor,
        entity_type="onboarding_draft",
        entity_id=draft.id,
        action="remove_staged_media",
        previous=previous,
        current=record_dict(media),
        row_version=draft.row_version,
        source_table=media.__tablename__,
        source_record_id=media.id,
    )
    return {"id": media.id, "row_version": draft.row_version}


def _validate_final_payload(session: Session, draft: db.EOATOnboardingDraft) -> tuple[dict[str, Any], dict[str, Any]]:
    payload = draft.payload_json or {}
    identity = payload.get("identity") if isinstance(payload.get("identity"), dict) else {}
    identity = {
        **identity,
        "business_identifier": _identifier(identity.get("business_identifier") or draft.proposed_identifier),
    }
    if not identity.get("business_identifier") or not identity.get("eoat_type"):
        raise APIError(422, "ONBOARDING_BLOCKING_ERRORS", "Identifier and EOAT type are required before finalization.")
    values = EOATCreate.model_validate(identity).model_dump()
    if values["business_identifier"] != draft.proposed_identifier:
        raise APIError(
            409, "IDENTIFIER_RESERVATION_CONFLICT", "The final identifier no longer matches the active reservation."
        )
    reservation = session.scalar(
        select(db.EOATIdentifierReservation)
        .where(db.EOATIdentifierReservation.normalized_identifier == values["business_identifier"])
        .with_for_update()
    )
    if reservation is None or reservation.draft_id != draft.id or reservation.released_at is not None:
        raise APIError(
            409, "IDENTIFIER_RESERVATION_CONFLICT", "The identifier reservation is no longer active for this draft."
        )
    if (
        session.scalar(select(db.EOAT.id).where(db.EOAT.business_identifier == values["business_identifier"]))
        is not None
    ):
        raise APIError(409, "DUPLICATE_IDENTIFIER", "An EOAT already uses this identifier.")
    engineering = payload.get("engineering") if isinstance(payload.get("engineering"), dict) else {}
    return values, {key: value for key, value in engineering.items() if key in ENGINEERING_FIELDS}


def finalize_draft(session: Session, actor: ActorContext, draft_uuid: str, expected: int) -> dict[str, Any]:
    draft = _draft(session, draft_uuid, lock=True)
    _check_draft_version(draft, expected)
    values, engineering = _validate_final_payload(session, draft)
    eoat = create_asset(session, actor, "eoat", values.copy())
    eoat_id = int(eoat["id"])
    if engineering:
        session.add(
            db.EOATEngineeringProfile(
                eoat_id=eoat_id, **engineering, created_by_user_id=actor.user_id, updated_by_user_id=actor.user_id
            )
        )
    relations = (draft.payload_json or {}).get("compatibility", [])
    if relations and not actor.permits("relationship.edit"):
        raise APIError(
            403, "PERMISSION_DENIED", "This draft includes compatibility changes that require relationship permission."
        )
    for raw in relations:
        relationship_type = str(raw.get("relationship_type", "eoat-machine"))
        target = raw.get("target")
        relationship_values = {key: value for key, value in raw.items() if key not in {"relationship_type", "target"}}
        if relationship_type == "eoat-machine":
            relationship_values["machine_number"] = target
        elif relationship_type == "eoat-tool":
            relationship_values["tool_identifier"] = target
        else:
            raise APIError(
                422,
                "INVALID_ONBOARDING_RELATIONSHIP",
                "Onboarding supports EOAT-to-Machine or EOAT-to-Tool relationships.",
            )
        data = CompatibilityWrite.model_validate(
            {**relationship_values, "eoat_identifier": values["business_identifier"]}
        ).model_dump(exclude_none=True)
        write_compatibility(session, actor, relationship_type, data)
    location = (draft.payload_json or {}).get("location") or {}
    if location.get("kind") == "machine":
        if not actor.permits("assignment.edit"):
            raise APIError(
                403, "PERMISSION_DENIED", "This draft includes an installation that requires assignment permission."
            )
        move_to_machine(
            session,
            actor,
            values["business_identifier"],
            {**location, "expected_row_version": int(eoat["row_version"])},
        )
    elif location.get("kind") == "storage":
        if not actor.permits("assignment.edit"):
            raise APIError(
                403, "PERMISSION_DENIED", "This draft includes storage assignment that requires assignment permission."
            )
        move_to_storage(
            session,
            actor,
            values["business_identifier"],
            {**location, "expected_row_version": int(eoat["row_version"])},
        )
    profile_photo_id: int | None = None
    media_rows = session.scalars(
        select(db.EOATOnboardingStagedMedia)
        .where(db.EOATOnboardingStagedMedia.draft_id == draft.id, db.EOATOnboardingStagedMedia.is_active.is_(True))
        .with_for_update()
    ).all()
    for media in media_rows:
        metadata = {
            "document_type": media.document_type,
            "title": media.title,
            "description": media.description,
            "revision": media.revision,
            "storage_path": media.storage_path,
            "mime_type": media.mime_type,
            "entity_type": "eoat",
            "entity_id": eoat_id,
        }
        if media.media_kind == "photo":
            created = create_photo(
                session, actor, {**metadata, "photo_view_type": media.photo_view_type, "caption": media.caption}
            )
            media.adopted_document_id = int(created["document"]["id"])
            if (media.photo_view_type or "").upper() == "FRONT" and profile_photo_id is None:
                profile_photo_id = int(created["photo"]["id"])
        else:
            created = create_document(session, actor, metadata)
            media.adopted_document_id = int(created["id"])
        media.row_version += 1
        media.updated_by_user_id = actor.user_id
    if profile_photo_id is not None:
        photo = session.get(db.Photo, profile_photo_id)
        document = session.get(db.Document, photo.document_id) if photo else None
        if document is not None:
            set_profile_photo(
                session, actor, profile_photo_id, int(document.row_version), "FRONT onboarding photo selected"
            )
    before = record_dict(draft)
    draft.lifecycle_state, draft.finalized_eoat_id, draft.finalized_at, draft.completion_state = (
        "FINALIZED",
        eoat_id,
        utcnow(),
        "FINALIZED",
    )
    draft.row_version += 1
    draft.updated_by_user_id = actor.user_id
    _release_other_reservations(session, draft, values["business_identifier"])
    reservation = session.scalar(
        select(db.EOATIdentifierReservation).where(
            db.EOATIdentifierReservation.normalized_identifier == values["business_identifier"]
        )
    )
    if reservation:
        reservation.released_at = utcnow()
    audit_change(
        session,
        actor,
        entity_type="onboarding_draft",
        entity_id=draft.id,
        action="finalize",
        previous=before,
        current=record_dict(draft),
        row_version=draft.row_version,
        source_table=draft.__tablename__,
        source_record_id=draft.id,
    )
    return {
        "draft": _draft_summary(draft),
        "eoat": eoat,
        "warnings": [] if profile_photo_id else ["No FRONT photo was staged; no profile image was selected."],
    }
