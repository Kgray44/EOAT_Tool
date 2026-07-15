from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from server.eoat_api.app import app
from server.eoat_api.database import models as db
from server.eoat_api.database.session import create_session_factory
from server.eoat_api.security import ActorContext
from server.eoat_api.write_services import move_to_machine
from tests.fixtures.mysql_sanctioned import (
    EVALUATION_TIME,
    FIXTURE_SOURCE,
    deterministic_uuid,
    reset_and_load_sanctioned_fixture,
)

pytestmark = pytest.mark.skipif(
    os.getenv("EOAT_DB_NAME") != "eoat_atlas_test",
    reason="Installation matrix requires EOAT_DB_NAME=eoat_atlas_test",
)

TECHNICIAN = {"X-EOAT-Identity": "dev.technician"}
ENGINEER = {"X-EOAT-Identity": "dev.engineer"}


@pytest.fixture(scope="module", autouse=True)
def sanctioned_database():
    reset_and_load_sanctioned_fixture()


@pytest.fixture(scope="module", autouse=True)
def explicit_development_write_environment():
    values = {"EOAT_API_ENVIRONMENT": "development", "EOAT_API_WRITES_ENABLED": "true"}
    previous = {name: os.environ.get(name) for name in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


@pytest.fixture(scope="module")
def api():
    with TestClient(app) as client:
        yield client


@pytest.fixture(scope="module", autouse=True)
def concurrency_records(sanctioned_database):
    factory = create_session_factory(migration=True)
    with factory() as session, session.begin():
        plant = session.scalar(select(db.Plant).where(db.Plant.plant_code == "DEMO-P4"))
        status_id = session.scalar(select(db.CompatibilityStatus.id).where(db.CompatibilityStatus.code == "compatible"))
        source_id = session.scalar(
            select(db.CompatibilitySource.id).where(db.CompatibilitySource.code == "synthetic_fixture")
        )
        machines = {}
        for number in ("C101", "C102", "C103"):
            machine = db.Machine(
                plant_id=plant.id,
                machine_number=number,
                machine_name=f"Synthetic Concurrency Machine {number}",
                source_system=FIXTURE_SOURCE,
            )
            session.add(machine)
            session.flush()
            machines[number] = machine
        tools = {}
        for number in ("CONCUR-TOOL-1", "CONCUR-TOOL-2", "CONCUR-TOOL-3"):
            tool = db.Tool(
                business_identifier=number,
                display_name=f"Synthetic {number}",
                source_system=FIXTURE_SOURCE,
            )
            session.add(tool)
            session.flush()
            tools[number] = tool
        eoats = {}
        for number in ("CONCUR-EOAT-A", "CONCUR-EOAT-B", "CONCUR-EOAT-C"):
            eoat = db.EOAT(
                business_identifier=number,
                display_name=f"Synthetic {number}",
                source_system=FIXTURE_SOURCE,
            )
            session.add(eoat)
            session.flush()
            eoats[number] = eoat

        tuples = (
            (eoats["CONCUR-EOAT-A"], machines["C101"], tools["CONCUR-TOOL-1"]),
            (eoats["CONCUR-EOAT-A"], machines["C102"], tools["CONCUR-TOOL-2"]),
            (eoats["CONCUR-EOAT-B"], machines["C103"], tools["CONCUR-TOOL-3"]),
            (eoats["CONCUR-EOAT-C"], machines["C103"], tools["CONCUR-TOOL-3"]),
        )
        for offset, (eoat, machine, tool) in enumerate(tuples):
            effective = EVALUATION_TIME - timedelta(days=20 + offset)
            common = {
                "compatibility_status_id": status_id,
                "verification_source_id": source_id,
                "effective_from": effective,
                "source_system": FIXTURE_SOURCE,
            }
            session.add(db.EOATMachineCompatibility(eoat_id=eoat.id, machine_id=machine.id, **common))
            session.add(db.EOATToolCompatibility(eoat_id=eoat.id, tool_id=tool.id, **common))
            existing = session.scalar(
                select(db.ToolMachineCompatibility.id).where(
                    db.ToolMachineCompatibility.tool_id == tool.id,
                    db.ToolMachineCompatibility.machine_id == machine.id,
                )
            )
            if existing is None:
                session.add(db.ToolMachineCompatibility(tool_id=tool.id, machine_id=machine.id, **common))


def _install(api, eoat, machine, tool, *, identity=TECHNICIAN, key=None, **extra):
    headers = dict(identity)
    headers["Idempotency-Key"] = key or f"matrix-{eoat}-{machine}-{tool}"
    payload = {
        "plant_code": extra.pop("plant_code", "DEMO-P4"),
        "machine_number": machine,
        "tool_identifier": tool,
        "expected_row_version": extra.pop("expected_row_version", 1),
        **extra,
    }
    return api.post(f"/api/v1/eoats/{eoat}/move-to-machine", headers=headers, json=payload)


@pytest.mark.parametrize(
    "eoat,machine,tool,plant_code,expected_status",
    (
        ("DEMO-P4-EOAT-0004", "043", "DEMO-TOOL-0004", "DEMO-P4", 403),
        ("DEMO-P5-EOAT-0001", "040", "DEMO-TOOL-0007", "DEMO-P5", 403),
        ("DEMO-P4-EOAT-0008", "046", "DEMO-TOOL-0008", "DEMO-P5", 403),
        ("DEMO-P4-EOAT-0012", "050", "DEMO-TOOL-0012", "DEMO-P5", 409),
        ("DEMO-P4-EOAT-0001", "040", "DEMO-TOOL-0001", None, 409),
        ("DEMO-P4-EOAT-0002", "DOES-NOT-EXIST", "DEMO-TOOL-0002", "DEMO-P4", 404),
    ),
)
def test_normal_installation_failure_matrix(api, eoat, machine, tool, plant_code, expected_status):
    response = _install(api, eoat, machine, tool, plant_code=plant_code)
    assert response.status_code == expected_status


def test_missing_tool_is_validation_error(api):
    response = api.post(
        "/api/v1/eoats/DEMO-P4-EOAT-0002/move-to-machine",
        headers=TECHNICIAN,
        json={"plant_code": "DEMO-P4", "machine_number": "041", "expected_row_version": 1},
    )
    assert response.status_code == 422


def test_wrong_robot_association_fails(api):
    response = _install(
        api,
        "DEMO-P4-EOAT-0002",
        "041",
        "DEMO-TOOL-0002",
        robot_identifier="DEMO-ROBOT-04",
    )
    assert response.status_code == 409
    assert response.json()["error_code"] == "ROBOT_MACHINE_MISMATCH"


def test_complete_compatible_tuple_succeeds_and_idempotency_prevents_duplicate_history(api):
    key = "installation-compatible-replay"
    first = _install(
        api,
        "DEMO-P4-EOAT-0002",
        "041",
        "DEMO-TOOL-0002",
        key=key,
        reason="Synthetic compatible installation",
    )
    assert first.status_code == 200, first.text
    replay = _install(
        api,
        "DEMO-P4-EOAT-0002",
        "041",
        "DEMO-TOOL-0002",
        key=key,
        reason="Synthetic compatible installation",
    )
    assert replay.status_code == 200
    assert replay.json()["id"] == first.json()["id"]
    with create_session_factory(migration=True)() as session:
        eoat_id = session.scalar(
            select(db.EOAT.id).where(db.EOAT.business_identifier == "DEMO-P4-EOAT-0002")
        )
        histories = session.scalar(
            select(func.count(db.EntityHistoryEvent.id)).where(
                db.EntityHistoryEvent.entity_type == "eoat",
                db.EntityHistoryEvent.entity_id == eoat_id,
                db.EntityHistoryEvent.request_id == first.headers["X-Request-ID"],
            )
        )
        assert histories == 1


def test_override_authorization_reason_and_provenance_matrix(api):
    base = {
        "eoat": "DEMO-P4-EOAT-0004",
        "machine": "043",
        "tool": "DEMO-TOOL-0004",
    }
    no_auth = _install(api, **base, identity={}, override_reason="Synthetic override")
    assert no_auth.status_code == 403
    unauthorized = _install(api, **base, identity=TECHNICIAN, override_reason="Synthetic override")
    assert unauthorized.status_code == 403
    missing = _install(api, **base, identity=ENGINEER)
    assert missing.status_code == 409
    blank = _install(api, **base, identity=ENGINEER, override_reason="   ")
    assert blank.status_code == 409

    instance_uuid = deterministic_uuid("application-instance")
    headers = {
        **ENGINEER,
        "X-Request-ID": deterministic_uuid("override-request"),
        "X-EOAT-Application-Instance": instance_uuid,
        "Idempotency-Key": "installation-authorized-override",
    }
    success = api.post(
        f"/api/v1/eoats/{base['eoat']}/move-to-machine",
        headers=headers,
        json={
            "plant_code": "DEMO-P4",
            "machine_number": base["machine"],
            "tool_identifier": base["tool"],
            "expected_row_version": 1,
            "override_reason": "Synthetic engineering approval",
        },
    )
    assert success.status_code == 200, success.text
    with create_session_factory(migration=True)() as session:
        event = session.scalar(
            select(db.EntityHistoryEvent)
            .where(db.EntityHistoryEvent.request_id == headers["X-Request-ID"])
            .order_by(db.EntityHistoryEvent.id.desc())
        )
        audit = session.scalar(
            select(db.ChangeAuditLog).where(
                db.ChangeAuditLog.request_id == headers["X-Request-ID"],
                db.ChangeAuditLog.action == "installation_compatibility_override",
            )
        )
        assert event.metadata_json["override_reason"] == "Synthetic engineering approval"
        assert event.metadata_json["fit_check"]["overall_result"] == "INCOMPATIBLE"
        assert all(
            key in event.metadata_json["fit_check"]
            for key in ("machine_tool_result", "machine_eoat_result", "tool_eoat_result")
        )
        assert event.metadata_json["actor_identity"] == "dev.engineer"
        assert event.metadata_json["request_id"] == headers["X-Request-ID"]
        assert event.metadata_json["application_instance_id"] is not None
        assert event.metadata_json["application_release_id"] is not None
        assert audit.application_release_id is not None


@pytest.mark.parametrize(
    "failure_stage",
    (
        "installation_creation",
        "eoat_version_update",
        "release_provenance_lookup",
        "audit_creation",
        "history_creation",
    ),
)
def test_injected_failure_rolls_back_entire_installation(failure_stage):
    factory = create_session_factory(migration=True)
    with factory() as baseline:
        eoat = baseline.scalar(
            select(db.EOAT).where(db.EOAT.business_identifier == "DEMO-P4-EOAT-0003")
        )
        before_version = eoat.row_version
        before_installations = baseline.scalar(select(func.count(db.EOATInstallation.id)))
        before_audits = baseline.scalar(select(func.count(db.ChangeAuditLog.id)))
        before_history = baseline.scalar(select(func.count(db.EntityHistoryEvent.id)))
        user = baseline.scalar(select(db.User).where(db.User.username == "demo.engineer"))
        instance = baseline.scalar(
            select(db.ApplicationInstance).where(
                db.ApplicationInstance.instance_uuid == deterministic_uuid("application-instance")
            )
        )
    actor = ActorContext(
        user_id=user.id,
        identity=user.external_identity,
        display_name=user.display_name,
        role="ENGINEER",
        request_id=deterministic_uuid(f"rollback-{failure_stage}"),
        application_instance_id=instance.id,
        client_version="0.15.0",
    )

    def inject(stage):
        if stage == failure_stage:
            raise RuntimeError(f"Injected {stage}")

    with pytest.raises(RuntimeError), factory() as session, session.begin():
        move_to_machine(
            session,
            actor,
            "DEMO-P4-EOAT-0003",
            {
                "plant_code": "DEMO-P4",
                "machine_number": "042",
                "tool_identifier": "DEMO-TOOL-0003",
                "expected_row_version": before_version,
                "reason": "Synthetic rollback test",
            },
            fault_injector=inject,
        )
    with factory() as verification:
        eoat = verification.scalar(
            select(db.EOAT).where(db.EOAT.business_identifier == "DEMO-P4-EOAT-0003")
        )
        assert eoat.row_version == before_version
        assert verification.scalar(select(func.count(db.EOATInstallation.id))) == before_installations
        assert verification.scalar(select(func.count(db.ChangeAuditLog.id))) == before_audits
        assert verification.scalar(select(func.count(db.EntityHistoryEvent.id))) == before_history


def test_two_simultaneous_installations_for_one_eoat_yield_one_success(api):
    attempts = (
        ("C101", "CONCUR-TOOL-1", "concurrent-eoat-a-1"),
        ("C102", "CONCUR-TOOL-2", "concurrent-eoat-a-2"),
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(
            executor.map(
                lambda item: _install(
                    api,
                    "CONCUR-EOAT-A",
                    item[0],
                    item[1],
                    key=item[2],
                    reason="Synthetic concurrent attempt",
                ),
                attempts,
            )
        )
    assert sorted(response.status_code for response in responses) == [200, 409]


def test_two_simultaneous_installations_for_one_machine_yield_one_success(api):
    attempts = (
        ("CONCUR-EOAT-B", "concurrent-machine-1"),
        ("CONCUR-EOAT-C", "concurrent-machine-2"),
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(
            executor.map(
                lambda item: _install(
                    api,
                    item[0],
                    "C103",
                    "CONCUR-TOOL-3",
                    key=item[1],
                    reason="Synthetic machine race",
                ),
                attempts,
            )
        )
    assert sum(response.status_code == 200 for response in responses) == 1
    assert sum(response.status_code in {409, 503} for response in responses) == 1
