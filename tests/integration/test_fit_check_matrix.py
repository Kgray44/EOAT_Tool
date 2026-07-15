from __future__ import annotations

import os
from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from server.eoat_api.contracts import FitCheckRequest
from server.eoat_api.database import models as db
from server.eoat_api.database.session import create_database_engine
from server.eoat_api.security import ActorContext
from server.eoat_api.services import AtlasService
from tests.fixtures.mysql_sanctioned import (
    EVALUATION_TIME,
    FIXTURE_SOURCE,
    deterministic_uuid,
    reset_and_load_sanctioned_fixture,
)

pytestmark = pytest.mark.skipif(
    os.getenv("EOAT_DB_NAME") != "eoat_atlas_test",
    reason="Fit Check matrix requires EOAT_DB_NAME=eoat_atlas_test",
)

PAIR_MODELS = {
    "machine_tool": db.ToolMachineCompatibility,
    "machine_eoat": db.EOATMachineCompatibility,
    "tool_eoat": db.EOATToolCompatibility,
}
PAIR_RESULT_ATTRIBUTES = {
    "machine_tool": "machine_tool_result",
    "machine_eoat": "machine_eoat_result",
    "tool_eoat": "tool_eoat_result",
}
STATUS_EXPECTATIONS = {
    "compatible": "COMPATIBLE",
    "verified_compatible": "COMPATIBLE",
    "approved": "COMPATIBLE",
    "incompatible": "INCOMPATIBLE",
    "failed": "INCOMPATIBLE",
    "not_compatible": "INCOMPATIBLE",
    "unknown": "UNKNOWN",
    "needs_review": "NEEDS_REVIEW",
    "pending": "UNKNOWN",
    "unrecognized_status": "UNKNOWN",
    None: "UNKNOWN",
}


@pytest.fixture(scope="module", autouse=True)
def sanctioned_database():
    reset_and_load_sanctioned_fixture()


@pytest.fixture
def session():
    engine = create_database_engine(migration=True)
    connection = engine.connect()
    transaction = connection.begin()
    value = Session(bind=connection, expire_on_commit=False)
    try:
        yield value
    finally:
        value.close()
        transaction.rollback()
        connection.close()


def _entities(session: Session, index: int = 2):
    machine = session.scalar(select(db.Machine).where(db.Machine.machine_number == f"{39 + index:03d}"))
    tool = session.scalar(select(db.Tool).where(db.Tool.business_identifier == f"DEMO-TOOL-{index:04d}"))
    eoat = session.scalar(select(db.EOAT).where(db.EOAT.business_identifier == f"DEMO-P4-EOAT-{index:04d}"))
    assert machine is not None and tool is not None and eoat is not None
    return machine, tool, eoat


def _request(index: int = 2) -> FitCheckRequest:
    return FitCheckRequest(
        machine_number=f"{39 + index:03d}",
        tool_number=f"DEMO-TOOL-{index:04d}",
        eoat_identifier=f"DEMO-P4-EOAT-{index:04d}",
    )


def _relationships(session: Session, index: int = 2):
    machine, tool, eoat = _entities(session, index)
    return {
        "machine_tool": session.scalar(
            select(db.ToolMachineCompatibility).where(
                db.ToolMachineCompatibility.machine_id == machine.id,
                db.ToolMachineCompatibility.tool_id == tool.id,
            )
        ),
        "machine_eoat": session.scalar(
            select(db.EOATMachineCompatibility).where(
                db.EOATMachineCompatibility.machine_id == machine.id,
                db.EOATMachineCompatibility.eoat_id == eoat.id,
            )
        ),
        "tool_eoat": session.scalar(
            select(db.EOATToolCompatibility).where(
                db.EOATToolCompatibility.tool_id == tool.id,
                db.EOATToolCompatibility.eoat_id == eoat.id,
            )
        ),
    }


def _set_compatible_baseline(session: Session, index: int = 2):
    compatible_id = session.scalar(select(db.CompatibilityStatus.id).where(db.CompatibilityStatus.code == "compatible"))
    relationships = _relationships(session, index)
    assert compatible_id is not None and all(relationships.values())
    for relationship in relationships.values():
        relationship.compatibility_status_id = compatible_id
        relationship.is_active = True
        relationship.effective_from = EVALUATION_TIME - timedelta(days=30)
        relationship.effective_to = None
    session.flush()
    return relationships


@pytest.mark.parametrize("pair_name", PAIR_MODELS)
@pytest.mark.parametrize("status_code,expected", STATUS_EXPECTATIONS.items())
def test_each_pair_status_fails_closed_independently(session, pair_name, status_code, expected):
    relationships = _set_compatible_baseline(session)
    selected = relationships[pair_name]
    if status_code is None:
        session.delete(selected)
    else:
        selected.compatibility_status_id = session.scalar(
            select(db.CompatibilityStatus.id).where(db.CompatibilityStatus.code == status_code)
        )
    session.flush()
    result = AtlasService(session).fit_check(_request(), evaluated_at=EVALUATION_TIME)
    pair_result = getattr(result, PAIR_RESULT_ATTRIBUTES[pair_name])
    assert pair_result.result == expected
    if expected == "COMPATIBLE":
        assert result.overall_result == "COMPATIBLE"
    elif expected == "INCOMPATIBLE":
        assert result.overall_result == "INCOMPATIBLE"
    else:
        assert result.overall_result == "NEEDS_REVIEW"


@pytest.mark.parametrize("pair_name", PAIR_MODELS)
@pytest.mark.parametrize(
    "scenario,from_delta,to_delta,is_active,expected",
    (
        ("open_ended", timedelta(days=-30), None, True, "COMPATIBLE"),
        ("currently_effective", timedelta(days=-1), timedelta(days=1), True, "COMPATIBLE"),
        ("future", timedelta(seconds=1), None, True, "UNKNOWN"),
        ("expired", timedelta(days=-2), timedelta(seconds=-1), True, "UNKNOWN"),
        ("exact_effective_from", timedelta(0), None, True, "COMPATIBLE"),
        ("exact_effective_to", timedelta(days=-1), timedelta(0), True, "COMPATIBLE"),
        ("inactive", timedelta(days=-1), None, False, "UNKNOWN"),
    ),
)
def test_each_pair_effective_date_and_active_matrix(
    session, pair_name, scenario, from_delta, to_delta, is_active, expected
):
    relationships = _set_compatible_baseline(session)
    selected = relationships[pair_name]
    selected.effective_from = EVALUATION_TIME + from_delta
    selected.effective_to = EVALUATION_TIME + to_delta if to_delta is not None else None
    selected.is_active = is_active
    session.flush()
    result = AtlasService(session).fit_check(_request(), evaluated_at=EVALUATION_TIME)
    assert getattr(result, PAIR_RESULT_ATTRIBUTES[pair_name]).result == expected, scenario


@pytest.mark.parametrize("entity_name", ("machine", "tool", "eoat"))
@pytest.mark.parametrize("state", ("inactive", "archived"))
def test_inactive_and_archived_entities_never_approve(session, entity_name, state):
    machine, tool, eoat = _entities(session)
    entity = {"machine": machine, "tool": tool, "eoat": eoat}[entity_name]
    if state == "inactive":
        entity.is_active = False
    else:
        entity.status_id = session.scalar(select(db.AssetStatus.id).where(db.AssetStatus.code == "archived"))
    session.flush()
    result = AtlasService(session).fit_check(_request(), evaluated_at=EVALUATION_TIME)
    assert result.overall_result == "INVALID_INPUT"
    assert entity_name in result.unknown_relationships


def test_plant_aware_machine_identity_and_ambiguity(session):
    service = AtlasService(session)
    ambiguous = service.fit_check(
        FitCheckRequest(
            machine_number="040",
            tool_number="DEMO-TOOL-0001",
            eoat_identifier="DEMO-P4-EOAT-0001",
        ),
        evaluated_at=EVALUATION_TIME,
    )
    assert ambiguous.overall_result == "INVALID_INPUT"
    assert "ambiguous" in ambiguous.reasons[0].casefold()

    plant_4 = service.fit_check(
        FitCheckRequest(
            plant_code="DEMO-P4",
            machine_number="040",
            tool_number="DEMO-TOOL-0001",
            eoat_identifier="DEMO-P4-EOAT-0001",
        ),
        evaluated_at=EVALUATION_TIME,
    )
    assert plant_4.overall_result == "COMPATIBLE"

    unique = service.fit_check(_request(), evaluated_at=EVALUATION_TIME)
    assert unique.overall_result in {"COMPATIBLE", "NEEDS_REVIEW"}


def test_alternatives_are_active_effective_compatible_sorted_and_deduplicated(session):
    relationships = _set_compatible_baseline(session)
    machine, tool, selected_eoat = _entities(session)
    compatible_id = session.scalar(select(db.CompatibilityStatus.id).where(db.CompatibilityStatus.code == "compatible"))
    incompatible_id = session.scalar(
        select(db.CompatibilityStatus.id).where(db.CompatibilityStatus.code == "incompatible")
    )
    source_id = relationships["machine_eoat"].verification_source_id

    candidates = session.scalars(
        select(db.EOAT)
        .where(db.EOAT.id != selected_eoat.id, db.EOAT.is_active.is_(True))
        .order_by(db.EOAT.business_identifier)
        .limit(30)
    ).all()
    for offset, eoat in enumerate(candidates):
        status_id = incompatible_id if offset == 4 else compatible_id
        effective_from = EVALUATION_TIME - timedelta(days=10)
        effective_to = None
        active = True
        if offset == 1:
            active = False
        elif offset == 2:
            effective_to = EVALUATION_TIME - timedelta(seconds=1)
        elif offset == 3:
            effective_from = EVALUATION_TIME + timedelta(seconds=1)
        session.add(
            db.EOATMachineCompatibility(
                eoat_id=eoat.id,
                machine_id=machine.id,
                compatibility_status_id=status_id,
                verification_source_id=source_id,
                effective_from=effective_from,
                effective_to=effective_to,
                is_active=active,
                source_system=FIXTURE_SOURCE,
            )
        )
        session.add(
            db.EOATToolCompatibility(
                eoat_id=eoat.id,
                tool_id=tool.id,
                compatibility_status_id=status_id,
                verification_source_id=source_id,
                effective_from=effective_from,
                effective_to=effective_to,
                is_active=active,
                source_system=FIXTURE_SOURCE,
            )
        )
    duplicate = candidates[0]
    session.add(
        db.EOATMachineCompatibility(
            eoat_id=duplicate.id,
            machine_id=machine.id,
            compatibility_status_id=compatible_id,
            verification_source_id=source_id,
            effective_from=EVALUATION_TIME - timedelta(days=20),
            is_active=True,
            source_system=FIXTURE_SOURCE,
        )
    )
    session.add(
        db.EOATToolCompatibility(
            eoat_id=duplicate.id,
            tool_id=tool.id,
            compatibility_status_id=compatible_id,
            verification_source_id=source_id,
            effective_from=EVALUATION_TIME - timedelta(days=20),
            is_active=True,
            source_system=FIXTURE_SOURCE,
        )
    )
    session.flush()

    result = AtlasService(session).fit_check(_request(), evaluated_at=EVALUATION_TIME)
    alternatives = result.alternative_compatible_eoats
    assert alternatives == sorted(set(alternatives))
    assert len(alternatives) > 20
    assert candidates[0].business_identifier in alternatives
    assert candidates[1].business_identifier not in alternatives
    assert candidates[2].business_identifier not in alternatives
    assert candidates[3].business_identifier not in alternatives
    assert candidates[4].business_identifier not in alternatives

    relationships["machine_tool"].is_active = False
    session.flush()
    blocked = AtlasService(session).fit_check(_request(), evaluated_at=EVALUATION_TIME)
    assert blocked.alternative_compatible_eoats == []


@pytest.mark.parametrize("target_status", ("compatible", "incompatible", "needs_review"))
def test_fit_check_persistence_records_actor_request_instance_and_result(session, target_status):
    relationships = _set_compatible_baseline(session)
    status_id = session.scalar(
        select(db.CompatibilityStatus.id).where(db.CompatibilityStatus.code == target_status)
    )
    if target_status != "compatible":
        relationships["machine_eoat"].compatibility_status_id = status_id
    demo_user = session.scalar(select(db.User).where(db.User.username == "demo.engineer"))
    instance = session.scalar(
        select(db.ApplicationInstance).where(db.ApplicationInstance.instance_uuid == deterministic_uuid("application-instance"))
    )
    request_id = deterministic_uuid(f"persist-{target_status}")
    actor = ActorContext(
        user_id=demo_user.id,
        identity=demo_user.external_identity,
        display_name=demo_user.display_name,
        role="ENGINEER",
        request_id=request_id,
        application_instance_id=instance.id,
        client_version="0.15.0",
    )
    service = AtlasService(session)
    result = service.fit_check(_request(), evaluated_at=EVALUATION_TIME)
    stored = service.persist_fit_check(_request(), result, actor)
    assert stored.stored is True
    record = session.scalar(select(db.FitCheckRecord).where(db.FitCheckRecord.request_id == request_id))
    assert record is not None
    assert record.performed_by_user_id == demo_user.id
    assert record.application_instance_id == instance.id
    assert record.result_summary == result.overall_result
