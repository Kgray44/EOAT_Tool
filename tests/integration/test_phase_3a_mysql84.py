"""Real MySQL 8.4 Phase 3A no-migration, migration, and failure truth tests."""

from __future__ import annotations

import os
from pathlib import Path

import pymysql
import pytest

from deployment.convergence.mysql_phase3a import DisposableMySQLError, DisposableMySQLMigration


def _connection():
    required = ("EOAT_MYSQL_HOST", "EOAT_MYSQL_USER", "EOAT_MYSQL_PASSWORD")
    if any(not os.environ.get(name) for name in required):
        pytest.skip("requires the dedicated disposable MySQL 8.4 Phase 3A service")
    return pymysql.connect(
        host=os.environ["EOAT_MYSQL_HOST"], port=int(os.environ.get("EOAT_MYSQL_PORT", "3306")),
        user=os.environ["EOAT_MYSQL_USER"], password=os.environ["EOAT_MYSQL_PASSWORD"], database="eoat_disposable",
        autocommit=False,
    )


def _reset(connection) -> None:
    with connection.cursor() as cursor:
        cursor.execute("DROP TABLE IF EXISTS data_state")
        cursor.execute("DROP TABLE IF EXISTS alembic_version")
        cursor.execute("CREATE TABLE alembic_version (version_num VARCHAR(64) NOT NULL)")
        cursor.execute("INSERT INTO alembic_version (version_num) VALUES ('phase3a-source')")
        cursor.execute("CREATE TABLE data_state (id INT PRIMARY KEY, current_revision INT NOT NULL)")
        cursor.execute("INSERT INTO data_state (id, current_revision) VALUES (1, 0)")
    connection.commit()


def test_real_mysql84_no_migration_migration_and_failure_recovery_truth(tmp_path: Path) -> None:
    connection = _connection()
    try:
        _reset(connection)
        rehearsal = DisposableMySQLMigration(connection, tmp_path)
        no_migration = rehearsal.rehearse("phase3a-source", [])
        assert no_migration.migration_mode == "NO_MIGRATION_REQUIRED"
        migrated = rehearsal.rehearse("phase3a-target", ["ALTER TABLE data_state ADD COLUMN phase3a_marker INT NOT NULL DEFAULT 1"])
        assert migrated.state == "MIGRATION_VERIFIED"
        assert migrated.backup_path and migrated.backup_sha256
        with connection.cursor() as cursor:
            cursor.execute("SELECT id, current_revision, phase3a_marker FROM data_state")
            assert cursor.fetchall() == ((1, 0, 1),)
        with pytest.raises(DisposableMySQLError, match="activation is blocked"):
            rehearsal.rehearse("phase3a-bad", ["THIS IS NOT VALID MYSQL"])
        assert rehearsal.revision() == "phase3a-target"
    finally:
        connection.close()
