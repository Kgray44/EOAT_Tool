from __future__ import annotations

import os
from uuid import uuid4

import pymysql
import pytest
from sqlalchemy import func, select

from scripts.database.import_eoat_location_observations import apply_plan
from server.eoat_api.database import models as db
from server.eoat_api.database.session import create_session_factory
from tests.fixtures.mysql_sanctioned import reset_and_load_sanctioned_fixture

pytestmark = pytest.mark.skipif(
    os.getenv("EOAT_DB_NAME") != "eoat_atlas_test",
    reason="Data freshness import integration tests require EOAT_DB_NAME=eoat_atlas_test",
)


@pytest.fixture(scope="module", autouse=True)
def seeded_database():
    reset_and_load_sanctioned_fixture()
    factory = create_session_factory(migration=True)
    with factory() as session, session.begin():
        plant = db.Plant(plant_code="FRESH-PLANT", plant_name="Freshness Plant")
        session.add(plant)
        session.flush()
        session.add(db.Machine(plant_id=plant.id, machine_number="FRESH-MACHINE"))
        session.add(db.EOAT(business_identifier="FRESH-IMPORT-EOAT"))


def _state() -> db.DataState:
    factory = create_session_factory(migration=True)
    with factory() as session:
        state = session.get(db.DataState, 1)
        assert state is not None
        session.expunge(state)
        return state


def _connection():
    return pymysql.connect(
        host=os.environ["EOAT_DB_HOST"],
        port=int(os.environ["EOAT_DB_PORT"]),
        user=os.environ["EOAT_DB_MIGRATION_USER"],
        password=os.environ["EOAT_DB_MIGRATION_PASSWORD"],
        database="eoat_atlas_test",
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )


def _plan(*, observation_uuid: str | None = None, include_unknown: bool = False) -> dict:
    observation_uuid = observation_uuid or str(uuid4())
    observations = [
        {
            "observation_uuid": observation_uuid,
            "eoat_identifier": "FRESH-IMPORT-EOAT",
            "state": "INSTALLED",
            "machine_number": "FRESH-MACHINE",
            "observed_on": "2026-07-21",
            "source_row_number": 1,
            "source_workbook": "freshness-fixture.xlsx",
            "source_worksheet": "EOAT Inventory",
            "original_source_wording": "Synthetic freshness import",
            "confidence": "SOURCE_ASSERTION",
            "resolution_status": "CURRENT",
            "conflict_group_uuid": None,
        }
    ]
    if include_unknown:
        observations.append({**observations[0], "observation_uuid": str(uuid4()), "eoat_identifier": "MISSING-EOAT"})
    return {
        "workbook": "freshness-fixture.xlsx",
        "workbook_sha256": "f" * 64,
        "observations": observations,
        "assertions": [
            {
                "assertion_uuid": str(uuid4()),
                "observation_uuid": observation_uuid,
                "eoat_identifier": "FRESH-IMPORT-EOAT",
                "state": "INSTALLED",
                "machine_number": "FRESH-MACHINE",
                "observed_on": "2026-07-21",
                "source_workbook": "freshness-fixture.xlsx",
                "source_worksheet": "EOAT Inventory",
                "source_row_number": 1,
                "original_source_wording": "Synthetic freshness import",
                "confidence": "SOURCE_ASSERTION",
                "participates_in_conflict": False,
            }
        ],
    }


def test_location_import_records_material_noop_and_failed_import_truthfully():
    before = _state()
    plan = _plan()
    with _connection() as connection:
        apply_plan(connection, plan)
    changed = _state()
    assert changed.current_revision == before.current_revision + 1
    assert changed.data_last_modified_at != before.data_last_modified_at
    assert changed.last_import_source == "freshness-fixture.xlsx:" + "f" * 64

    with _connection() as connection:
        apply_plan(connection, plan)
    no_op = _state()
    assert no_op.current_revision == changed.current_revision
    assert no_op.data_last_modified_at == changed.data_last_modified_at
    assert no_op.last_import_at is not None
    assert no_op.last_import_source == changed.last_import_source

    bad_plan = _plan(observation_uuid=str(uuid4()), include_unknown=True)
    with _connection() as connection:
        with pytest.raises(KeyError, match="MISSING-EOAT"):
            apply_plan(connection, bad_plan)
        connection.rollback()
    failed = _state()
    assert failed.current_revision == no_op.current_revision
    assert failed.data_last_modified_at == no_op.data_last_modified_at

    factory = create_session_factory(migration=True)
    with factory() as session:
        assert session.scalar(select(func.count(db.EOATLocationObservation.id))) == 1
