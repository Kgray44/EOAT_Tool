from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from server.eoat_api.database import models as db
from server.eoat_api.errors import APIError
from server.eoat_api.onboarding_services import (
    _assert_draft_editor,
    _assert_draft_viewer,
    create_draft,
    finalize_draft,
    list_drafts,
    select_eoat_profile_photo,
    stage_uploaded_media,
    update_draft,
)
from server.eoat_api.security import ActorContext, require_any


@pytest.fixture
def session():
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def sqlite_utc_timestamp(connection, _record):
        connection.create_function("UTC_TIMESTAMP", 0, lambda: datetime.now(timezone.utc).isoformat())
        connection.create_function("UTC_TIMESTAMP", 1, lambda _precision: datetime.now(timezone.utc).isoformat())

    db.Base.metadata.create_all(
        engine,
        tables=[
            db.User.__table__,
            db.EOATType.__table__,
            db.DocumentType.__table__,
            db.EOAT.__table__,
            db.EOATEngineeringProfile.__table__,
            db.Document.__table__,
            db.Photo.__table__,
            db.DocumentLink.__table__,
            db.EOATOnboardingDraft.__table__,
            db.EOATIdentifierReservation.__table__,
            db.EOATOnboardingStagedMedia.__table__,
        ],
    )
    with Session(engine) as value:
        next_identifier = 1

        @event.listens_for(value, "before_flush")
        def sqlite_bigint_ids(_session, _flush_context, _instances):
            nonlocal next_identifier
            for record in value.new:
                if isinstance(
                    record,
                    db.EOAT
                    | db.EOATEngineeringProfile
                    | db.Document
                    | db.DocumentLink
                    | db.EOATOnboardingDraft
                    | db.EOATIdentifierReservation
                    | db.EOATOnboardingStagedMedia
                    | db.EOATType
                    | db.DocumentType
                    | db.Photo
                ) and record.id is None:
                    record.id = next_identifier
                    next_identifier += 1

        value.add(db.EOATType(code="vacuum", display_name="Vacuum"))
        value.add(db.DocumentType(code="photo", display_name="Photo"))
        yield value


@pytest.fixture
def actor():
    return ActorContext(
        user_id=1,
        identity="test.technician",
        display_name="Test Technician",
        role="TECHNICIAN",
        request_id="onboarding-draft-test",
        application_instance_id=None,
        client_version=None,
    )


@pytest.fixture
def engineer():
    return ActorContext(
        user_id=2,
        identity="test.engineer",
        display_name="Test Engineer",
        role="ENGINEER",
        request_id="onboarding-finalization-test",
        application_instance_id=None,
        client_version=None,
    )


def _disable_audit(monkeypatch):
    monkeypatch.setattr("server.eoat_api.onboarding_services.audit_change", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("server.eoat_api.write_services.audit_change", lambda *_args, **_kwargs: None)


def _ready_draft(session, actor):
    draft = create_draft(
        session,
        actor,
        {
            "proposed_identifier": "P4-EOAT-0201",
            "plant_code": "P4",
            "payload": {
                "identity": {
                    "business_identifier": "P4-EOAT-0201",
                    "eoat_type": "vacuum",
                    "number_of_vacuum_cups": 0,
                    "number_of_grippers": None,
                    "vacuum_present": False,
                }
            },
        },
    )
    session.flush()
    return draft


def test_draft_reserves_identifier_resumes_and_rejects_stale_updates(monkeypatch, session, actor):
    _disable_audit(monkeypatch)
    payload = {
        "proposed_identifier": "P4-EOAT-0101",
        "plant_code": "P4",
        "payload": {"identity": {"business_identifier": "P4-EOAT-0101", "eoat_type": "vacuum"}},
    }

    draft = create_draft(session, actor, payload)
    session.flush()

    assert draft["proposed_identifier"] == "P4-EOAT-0101"
    assert draft["completion_state"] == "READY_FOR_REVIEW"
    with pytest.raises(APIError, match="reserved"):
        create_draft(session, actor, {**payload, "payload": {"identity": {"eoat_type": "vacuum"}}})

    resumed = update_draft(
        session,
        actor,
        draft["draft_uuid"],
        {
            "expected_row_version": draft["row_version"],
            "proposed_identifier": "P4-EOAT-0101",
            "plant_code": "P4",
            "payload": {"identity": {"business_identifier": "P4-EOAT-0101", "eoat_type": "vacuum", "notes": "Resumed"}},
        },
    )
    assert resumed["row_version"] == draft["row_version"] + 1
    assert resumed["payload"]["identity"]["notes"] == "Resumed"

    with pytest.raises(APIError, match="changed by another user"):
        update_draft(
            session,
            actor,
            draft["draft_uuid"],
            {**payload, "expected_row_version": draft["row_version"]},
        )

    other_actor = ActorContext(
        user_id=2,
        identity="test.other-technician",
        display_name="Other Technician",
        role="TECHNICIAN",
        request_id="onboarding-draft-other-user",
        application_instance_id=None,
        client_version=None,
    )
    with pytest.raises(APIError, match="cannot edit"):
        update_draft(
            session,
            other_actor,
            draft["draft_uuid"],
            {**payload, "expected_row_version": resumed["row_version"]},
        )


def test_finalizer_can_review_another_draft_without_editing_it(monkeypatch, session, actor):
    _disable_audit(monkeypatch)
    created = create_draft(
        session,
        actor,
        {
            "proposed_identifier": "P4-EOAT-0102",
            "plant_code": "P4",
            "payload": {"identity": {"business_identifier": "P4-EOAT-0102", "eoat_type": "vacuum"}},
        },
    )
    session.flush()
    draft = type("Draft", (), {"created_by_user_id": 1})()
    finalizer = ActorContext(
        user_id=2,
        identity="test.finalizer",
        display_name="Finalizer",
        role="VIEWER",
        request_id="onboarding-finalizer-test",
        application_instance_id=None,
        client_version=None,
        granted_permissions=frozenset({"onboarding.draft.finalize"}),
    )

    _assert_draft_viewer(finalizer, draft)
    assert (
        require_any("onboarding.draft.view", "onboarding.draft.review", "onboarding.draft.finalize")(finalizer)
        is finalizer
    )
    assert [row["draft_uuid"] for row in list_drafts(session, finalizer)] == [created["draft_uuid"]]
    with pytest.raises(APIError, match="cannot edit"):
        _assert_draft_editor(finalizer, draft)


def test_draft_editor_is_allowed_through_the_draft_visibility_route_gate():
    editor = ActorContext(
        user_id=1,
        identity="test.editor",
        display_name="Draft Editor",
        role="VIEWER",
        request_id="onboarding-draft-editor-test",
        application_instance_id=None,
        client_version=None,
        granted_permissions=frozenset({"onboarding.draft.edit"}),
    )

    assert require_any(
        "onboarding.draft.view",
        "onboarding.draft.edit",
        "onboarding.draft.review",
        "onboarding.draft.finalize",
    )(editor) is editor


def test_finalization_creates_a_real_eoat_and_releases_the_reservation(monkeypatch, session, actor, engineer):
    _disable_audit(monkeypatch)
    draft = _ready_draft(session, actor)

    result = finalize_draft(session, engineer, draft["draft_uuid"], draft["row_version"])

    created = session.scalar(select(db.EOAT).where(db.EOAT.business_identifier == "P4-EOAT-0201"))
    persisted_draft = session.scalar(
        select(db.EOATOnboardingDraft).where(db.EOATOnboardingDraft.draft_uuid == draft["draft_uuid"])
    )
    reservation = session.scalar(
        select(db.EOATIdentifierReservation).where(
            db.EOATIdentifierReservation.normalized_identifier == "P4-EOAT-0201"
        )
    )

    assert created is not None
    assert created.number_of_vacuum_cups == 0
    assert created.number_of_grippers is None
    assert created.vacuum_present is False
    assert result["eoat"]["id"] == created.id
    assert persisted_draft is not None and persisted_draft.lifecycle_state == "FINALIZED"
    assert persisted_draft.finalized_eoat_id == created.id
    assert reservation is not None and reservation.released_at is not None


def test_finalization_retains_command_center_data_with_controlled_defaults(monkeypatch, session, actor, engineer):
    _disable_audit(monkeypatch)
    draft = _ready_draft(session, actor)
    updated = update_draft(
        session,
        actor,
        draft["draft_uuid"],
        {
            "expected_row_version": draft["row_version"],
            "proposed_identifier": "P4-EOAT-0201",
            "plant_code": "P4",
            "payload": {
                **draft["payload"],
                "command_center": {
                    "eoat_moves": "Part",
                    "air_circuit_architecture": "Robot Only",
                    "external_pressure_circuits": "N/A",
                    "part_family": "Closure",
                    "tubing_condition": "OK",
                },
            },
        },
    )
    session.flush()

    finalized = finalize_draft(session, engineer, updated["draft_uuid"], updated["row_version"])
    profile = session.scalar(
        select(db.EOATEngineeringProfile).where(db.EOATEngineeringProfile.eoat_id == finalized["eoat"]["id"])
    )

    assert profile is not None
    assert profile.command_center_data["part_family"] == "Closure"
    assert profile.command_center_data["eoat_moves"] == "Part"
    assert profile.command_center_data["external_pressure_circuits"] == "N/A"
    assert profile.command_center_data["changeover_difficulty"] == "Unknown / Not Checked"


def test_finalization_requires_an_explicit_finalization_grant(monkeypatch, session, actor):
    _disable_audit(monkeypatch)
    draft = _ready_draft(session, actor)

    with pytest.raises(APIError, match="cannot finalize"):
        finalize_draft(session, actor, draft["draft_uuid"], draft["row_version"])

    assert session.scalar(select(db.EOAT).where(db.EOAT.business_identifier == "P4-EOAT-0201")) is None


def test_uploaded_media_stays_in_controlled_staging_and_paths_are_not_returned(monkeypatch, tmp_path, session, actor):
    _disable_audit(monkeypatch)
    monkeypatch.setenv("EOAT_ONBOARDING_STAGING_ROOT", str(tmp_path))
    monkeypatch.setenv("EOAT_DOCUMENT_ROOTS", str(tmp_path))
    draft = _ready_draft(session, actor)

    result = stage_uploaded_media(
        session,
        actor,
        draft["draft_uuid"],
        {
            "expected_row_version": draft["row_version"],
            "content_base64": "c3RhZ2VkLWJ5dGVz",
            "media_kind": "photo",
            "document_type": "photo",
            "file_name": "front.jpg",
            "title": "Front view",
            "photo_view_type": "FRONT",
        },
    )

    media = session.get(db.EOATOnboardingStagedMedia, result["id"])
    assert media is not None
    assert media.storage_path.startswith(str(tmp_path))
    assert Path(media.storage_path).name == "front.jpg"
    assert Path(media.storage_path).read_bytes() == b"staged-bytes"
    summary = list_drafts(session, actor)[0]
    assert "storage_path" not in summary["staged_media"][0]

    staged_before_failure = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*") if path.is_file())
    with pytest.raises(APIError, match="changed by another user"):
        stage_uploaded_media(
            session,
            actor,
            draft["draft_uuid"],
            {
                "expected_row_version": draft["row_version"],
                "content_base64": "c2hvdWxkLW5vdC1yZW1haW4=",
                "media_kind": "photo",
                "document_type": "photo",
                "file_name": "failed.jpg",
                "title": "Failed staging",
                "photo_view_type": "FRONT",
            },
        )
    assert sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*") if path.is_file()) == staged_before_failure


def test_profile_photo_selection_uses_only_a_linked_eoat_photo(monkeypatch, session, actor, engineer):
    _disable_audit(monkeypatch)
    draft = _ready_draft(session, actor)
    finalized = finalize_draft(session, engineer, draft["draft_uuid"], draft["row_version"])
    eoat_id = finalized["eoat"]["id"]
    document_type_id = session.scalar(select(db.DocumentType.id).where(db.DocumentType.code == "photo"))
    first = db.Document(
        document_uuid="11111111-1111-1111-1111-111111111111",
        document_type_id=document_type_id,
        title="Front",
        file_name="front.jpg",
        storage_path="C:/controlled/front.jpg",
        created_by_user_id=engineer.user_id,
        updated_by_user_id=engineer.user_id,
    )
    second = db.Document(
        document_uuid="22222222-2222-2222-2222-222222222222",
        document_type_id=document_type_id,
        title="Side",
        file_name="side.jpg",
        storage_path="C:/controlled/side.jpg",
        created_by_user_id=engineer.user_id,
        updated_by_user_id=engineer.user_id,
    )
    session.add_all([first, second])
    session.flush()
    first_photo = db.Photo(document_id=first.id, is_profile_photo=True, captured_by_user_id=engineer.user_id)
    second_photo = db.Photo(document_id=second.id, is_profile_photo=False, captured_by_user_id=engineer.user_id)
    session.add_all([first_photo, second_photo])
    session.add_all(
        [
            db.DocumentLink(document_id=first.id, entity_type="eoat", entity_id=eoat_id, relationship_type="attachment"),
            db.DocumentLink(document_id=second.id, entity_type="eoat", entity_id=eoat_id, relationship_type="attachment"),
        ]
    )
    session.flush()

    result = select_eoat_profile_photo(session, engineer, "P4-EOAT-0201", second.document_uuid, "Updated front view")

    assert result["row_version"] >= 1
    assert session.get(db.Photo, first_photo.id).is_profile_photo is False
    assert session.get(db.Photo, second_photo.id).is_profile_photo is True
    with pytest.raises(APIError, match="not found"):
        select_eoat_profile_photo(session, engineer, "P4-EOAT-0201", "missing-photo", None)


def test_failed_finalization_rolls_back_created_asset_and_keeps_draft_recoverable(monkeypatch, session, actor, engineer):
    _disable_audit(monkeypatch)
    draft = _ready_draft(session, actor)
    from server.eoat_api import onboarding_services

    original_create_asset = onboarding_services.create_asset

    def create_then_fail(*args, **kwargs):
        original_create_asset(*args, **kwargs)
        raise RuntimeError("forced post-create failure")

    monkeypatch.setattr(onboarding_services, "create_asset", create_then_fail)

    with pytest.raises(RuntimeError, match="forced post-create failure"), session.begin_nested():
        finalize_draft(session, engineer, draft["draft_uuid"], draft["row_version"])

    session.expire_all()
    assert session.scalar(select(db.EOAT).where(db.EOAT.business_identifier == "P4-EOAT-0201")) is None
    persisted_draft = session.scalar(
        select(db.EOATOnboardingDraft).where(db.EOATOnboardingDraft.draft_uuid == draft["draft_uuid"])
    )
    reservation = session.scalar(
        select(db.EOATIdentifierReservation).where(
            db.EOATIdentifierReservation.normalized_identifier == "P4-EOAT-0201"
        )
    )
    assert persisted_draft is not None and persisted_draft.lifecycle_state == "DRAFT"
    assert reservation is not None and reservation.released_at is None
