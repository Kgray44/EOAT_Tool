"""Disposable MySQL 8.4 migration rehearsal with explicit recovery truth."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from deployment.common import DeploymentError, sha256_file, utc_text, write_json_atomic


class DisposableMySQLError(DeploymentError):
    pass


@dataclass(frozen=True)
class MySQLRehearsalResult:
    source_schema: str
    target_schema: str
    migration_mode: str
    backup_path: str | None
    backup_sha256: str | None
    state: str
    database_recovery_required: bool


class DisposableMySQLMigration:
    """Use a caller-owned disposable MySQL connection; never discovers targets."""

    def __init__(self, connection, evidence_root: Path) -> None:
        self.connection = connection
        self.evidence_root = evidence_root

    def revision(self) -> str:
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT version_num FROM alembic_version LIMIT 1")
            row = cursor.fetchone()
        if not row or not row[0]:
            raise DisposableMySQLError("disposable database does not expose an Alembic revision")
        return str(row[0])

    def backup(self) -> tuple[Path, str]:
        """Create a bounded logical backup evidence artifact before migration."""

        with self.connection.cursor() as cursor:
            cursor.execute("SELECT version_num FROM alembic_version")
            version = [str(row[0]) for row in cursor.fetchall()]
            cursor.execute("SHOW TABLES")
            tables = [str(row[0]) for row in cursor.fetchall()]
            singleton: list[object] = []
            if "data_state" in tables:
                cursor.execute("SELECT id, current_revision FROM data_state ORDER BY id")
                singleton = list(cursor.fetchall())
        path = self.evidence_root / "mysql-backups" / f"backup-{utc_text().replace(':', '')}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json_atomic(path, {"schema_version": 1, "kind": "DISPOSABLE_LOGICAL_SCHEMA_BACKUP", "alembic_version": version, "tables": tables, "data_state": singleton})
        digest = sha256_file(path)
        if not path.is_file() or len(digest) != 64:
            raise DisposableMySQLError("disposable backup verification failed")
        return path, digest

    def rehearse(self, target_schema: str, statements: Iterable[str]) -> MySQLRehearsalResult:
        source = self.revision()
        if source == target_schema:
            return MySQLRehearsalResult(source, target_schema, "NO_MIGRATION_REQUIRED", None, None, "NO_MIGRATION_EXECUTED", False)
        backup, digest = self.backup()
        try:
            with self.connection.cursor() as cursor:
                for statement in statements:
                    cursor.execute(statement)
                cursor.execute("UPDATE alembic_version SET version_num = %s", (target_schema,))
            self.connection.commit()
        except Exception as exc:
            self.connection.rollback()
            raise DisposableMySQLError("migration execution failed; application activation is blocked and recovery must be assessed") from exc
        if self.revision() != target_schema:
            raise DisposableMySQLError("migration target schema verification failed")
        return MySQLRehearsalResult(source, target_schema, "MIGRATION_REQUIRED", str(backup), digest, "MIGRATION_VERIFIED", False)
