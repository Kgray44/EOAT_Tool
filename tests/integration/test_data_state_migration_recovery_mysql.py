from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pymysql
import pytest
from fastapi.testclient import TestClient

from server.eoat_api.app import app

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(
    os.getenv("EOAT_DB_NAME") != "eoat_atlas_test",
    reason="Data-state migration recovery requires EOAT_DB_NAME=eoat_atlas_test",
)


def _run(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *arguments],
        cwd=ROOT,
        env=os.environ.copy(),
        check=check,
        capture_output=True,
        text=True,
    )


def _reset() -> None:
    _run("scripts/database/reset_mysql_test_database.py", "--database", "eoat_atlas_test")


def _migration_connection():
    return pymysql.connect(
        host=os.environ["EOAT_DB_HOST"],
        port=int(os.environ["EOAT_DB_PORT"]),
        user=os.environ["EOAT_DB_MIGRATION_USER"],
        password=os.environ["EOAT_DB_MIGRATION_PASSWORD"],
        database="eoat_atlas_test",
        charset="utf8mb4",
    )


def _revision() -> str:
    with _migration_connection() as connection, connection.cursor() as cursor:
        cursor.execute("SELECT version_num FROM alembic_version")
        return cursor.fetchone()[0]


def test_failed_0008_seed_cleans_up_its_partial_data_state_table() -> None:
    """A direct Alembic failure must not strand MySQL DDL at revision 0007."""
    _reset()
    try:
        _run("-m", "alembic", "-c", "server/alembic.ini", "downgrade", "20260717_0007")
        with _migration_connection() as connection, connection.cursor() as cursor:
            cursor.execute("DROP TABLE change_feed")
        result = _run("-m", "alembic", "-c", "server/alembic.ini", "upgrade", "20260721_0008", check=False)
        assert result.returncode != 0
        with _migration_connection() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT version_num FROM alembic_version")
            assert cursor.fetchone()[0] == "20260717_0007"
            cursor.execute("SHOW TABLES LIKE 'data_state'")
            assert cursor.fetchone() is None
    finally:
        _reset()


def test_0007_upgrade_round_trip_preserves_existing_rows_and_singleton_invariant() -> None:
    _reset()
    try:
        _run("-m", "alembic", "-c", "server/alembic.ini", "downgrade", "20260717_0007")
        with _migration_connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO plants (plant_code, plant_name) VALUES (%s, %s)",
                ("MIGRATION-0008", "Migration preservation fixture"),
            )
            connection.commit()
        _run("-m", "alembic", "-c", "server/alembic.ini", "upgrade", "20260721_0008")
        with _migration_connection() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT plant_name FROM plants WHERE plant_code = %s", ("MIGRATION-0008",))
            assert cursor.fetchone()[0] == "Migration preservation fixture"
            cursor.execute("SELECT id, current_revision FROM data_state")
            assert cursor.fetchall() == ((1, 0),)
        _run("-m", "alembic", "-c", "server/alembic.ini", "downgrade", "20260717_0007")
        assert _revision() == "20260717_0007"
        with _migration_connection() as connection, connection.cursor() as cursor:
            cursor.execute("SHOW TABLES LIKE 'data_state'")
            assert cursor.fetchone() is None
            cursor.execute("SELECT plant_name FROM plants WHERE plant_code = %s", ("MIGRATION-0008",))
            assert cursor.fetchone()[0] == "Migration preservation fixture"
        _run("-m", "alembic", "-c", "server/alembic.ini", "upgrade", "20260721_0008")
        assert _revision() == "20260721_0008"
        with _migration_connection() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT id FROM data_state")
            assert cursor.fetchall() == ((1,),)
    finally:
        _reset()


def test_already_current_0009_api_startup_does_not_migrate() -> None:
    _reset()
    before = _revision()
    with TestClient(app) as client:
        assert client.get("/api/v1/health").status_code == 200
    assert before == _revision() == "20260729_0009"
