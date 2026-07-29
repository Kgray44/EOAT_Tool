from __future__ import annotations

import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import DBAPIError, IntegrityError

import server.eoat_api.database.models as models
from server.eoat_api.database.base import Base

TEST_URL = os.getenv("EOAT_MYSQL_TEST_URL")
RUNTIME_URL = os.getenv("EOAT_MYSQL_RUNTIME_URL")
pytestmark = pytest.mark.skipif(not TEST_URL, reason="EOAT_MYSQL_TEST_URL is required for real MySQL integration tests")


@pytest.fixture(scope="module")
def engine():
    value = create_engine(TEST_URL, pool_pre_ping=True)
    yield value
    value.dispose()


def test_migration_created_complete_mysql_schema(engine):
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    assert set(Base.metadata.tables) <= tables
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "20260729_0009"
        assert connection.execute(text("SELECT VERSION()" )).scalar_one().startswith("8.4.")


def test_data_state_is_a_seeded_non_auto_increment_singleton(engine):
    """The freshness migration must work on real MySQL, not only SQLite."""
    with engine.connect() as connection:
        create_statement = connection.execute(text("SHOW CREATE TABLE data_state")).mappings().one()["Create Table"]
        state = connection.execute(
            text(
                "SELECT id, current_revision, data_last_modified_at, last_import_at, last_import_source "
                "FROM data_state"
            )
        ).mappings().all()
    assert "AUTO_INCREMENT" not in create_statement.upper()
    assert "CK_DATA_STATE_SINGLETON" in create_statement.upper()
    assert "`ID` = 1" in create_statement.upper()
    assert len(state) == 1
    assert state[0]["id"] == 1
    # This module can run after other MySQL integration modules.  The
    # structural invariant is a valid non-negative singleton revision; the
    # fresh-empty reset path separately exercises its initial value of zero.
    assert state[0]["current_revision"] >= 0
    assert state[0]["data_last_modified_at"] is not None
    assert state[0]["last_import_at"] is None
    assert state[0]["last_import_source"] is None


def test_foreign_key_and_unique_constraints(engine):
    token = uuid4().hex[:10]
    with engine.begin() as connection:
        connection.execute(models.ImportBatch.__table__.insert().values(
            batch_uuid=str(uuid4()), batch_name=f"test-{token}", source_type="TEST", source_file_name="test.xlsx",
            source_file_checksum="0" * 64, started_at=text("UTC_TIMESTAMP(6)"), status="TEST", dry_run=True,
        ))
        connection.execute(models.Plant.__table__.insert().values(plant_code=f"P{token}", plant_name="Integration Plant"))
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(models.Plant.__table__.insert().values(plant_code=f"P{token}", plant_name="Duplicate"))
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(models.Area.__table__.insert().values(plant_id=999999999, area_code=token, area_name="Bad FK"))


def test_active_installation_generated_unique_constraints(engine):
    token = uuid4().hex[:10]
    with engine.begin() as connection:
        plant_id = connection.execute(models.Plant.__table__.insert().values(plant_code=f"I{token}", plant_name="Install Plant")).lastrowid
        eoat_id = connection.execute(models.EOAT.__table__.insert().values(business_identifier=f"EOAT-{token}")).lastrowid
        machine_a = connection.execute(models.Machine.__table__.insert().values(plant_id=plant_id, machine_number=f"A{token}")).lastrowid
        machine_b = connection.execute(models.Machine.__table__.insert().values(plant_id=plant_id, machine_number=f"B{token}")).lastrowid
        connection.execute(models.EOATInstallation.__table__.insert().values(eoat_id=eoat_id, machine_id=machine_a, installed_at=text("UTC_TIMESTAMP(6)"), source="TEST"))
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(models.EOATInstallation.__table__.insert().values(eoat_id=eoat_id, machine_id=machine_b, installed_at=text("UTC_TIMESTAMP(6)"), source="TEST"))


def test_transaction_rollback(engine):
    token = uuid4().hex[:10]
    with pytest.raises(RuntimeError), engine.begin() as connection:
        connection.execute(models.Plant.__table__.insert().values(plant_code=f"R{token}", plant_name="Rollback"))
        raise RuntimeError("force rollback")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM plants WHERE plant_code = :code"), {"code": f"R{token}"}).scalar_one() == 0


@pytest.mark.skipif(not RUNTIME_URL, reason="EOAT_MYSQL_RUNTIME_URL is required for privilege verification")
def test_runtime_account_cannot_create_tables():
    runtime = create_engine(RUNTIME_URL)
    try:
        with pytest.raises(DBAPIError), runtime.begin() as connection:
            connection.execute(text("CREATE TABLE runtime_account_must_not_create (id INT PRIMARY KEY)"))
    finally:
        runtime.dispose()
