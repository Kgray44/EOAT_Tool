from __future__ import annotations

from datetime import datetime, timezone

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
            db.EOAT.__table__,
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
                    db.EOAT | db.EOATOnboardingDraft | db.EOATIdentifierReservation | db.EOATType,
                ) and record.id is None:
                    record.id = next_identifier
                    next_identifier += 1

        value.add(db.EOATType(code="vacuum", display_name="Vacuum"))
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


def test_finalization_requires_an_explicit_finalization_grant(monkeypatch, session, actor):
    _disable_audit(monkeypatch)
    draft = _ready_draft(session, actor)

    with pytest.raises(APIError, match="cannot finalize"):
        finalize_draft(session, actor, draft["draft_uuid"], draft["row_version"])

    assert session.scalar(select(db.EOAT).where(db.EOAT.business_identifier == "P4-EOAT-0201")) is None


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
