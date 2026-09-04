from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from server.eoat_api.database import models as db
from server.eoat_api.errors import APIError
from server.eoat_api.onboarding_services import create_draft, update_draft
from server.eoat_api.security import ActorContext


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
                if isinstance(record, db.EOATOnboardingDraft | db.EOATIdentifierReservation) and record.id is None:
                    record.id = next_identifier
                    next_identifier += 1

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


def test_draft_reserves_identifier_resumes_and_rejects_stale_updates(monkeypatch, session, actor):
    monkeypatch.setattr("server.eoat_api.onboarding_services.audit_change", lambda *_args, **_kwargs: None)
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
