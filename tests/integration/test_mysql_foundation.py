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
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "20260811_0006"
        assert connection.execute(text("SELECT VERSION()" )).scalar_one().startswith("8.4.")
    assert {"audit_events", "audit_changes"} <= tables
    assert {"ix_audit_events_entity_time", "ix_audit_events_actor_time", "ix_audit_events_category_time"} <= {
        item["name"] for item in inspector.get_indexes("audit_events")
    }


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


def test_global_audit_event_identity_is_unique(engine):
    event_id = str(uuid4())
    values = {
        "event_id": event_id,
        "actor_type": "system",
        "action": "SCHEMA_MIGRATED",
        "entity_type": "schema",
        "entity_id": "20260811_0006",
        "source_client": "migration",
        "result": "SUCCESS",
        "action_category": "SYSTEM_OPERATIONS",
    }
    with engine.begin() as connection:
        connection.execute(models.AuditEvent.__table__.insert().values(**values))
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(models.AuditEvent.__table__.insert().values(**values))


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
