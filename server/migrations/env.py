from __future__ import annotations

import hashlib
from logging.config import fileConfig
import re

from alembic import context
from sqlalchemy import engine_from_config, event, pool, text

import server.eoat_api.database.models  # noqa: F401
from server.eoat_api.database.base import Base
from server.eoat_api.database.config import migration_database_url

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)
config.set_main_option("sqlalchemy.url", migration_database_url().replace("%", "%%"))
target_metadata = Base.metadata

_PRODUCTION_HEAD = "20260729_0009"
_ADMIN_HEAD = "20260820_0012"
_ADOPTABLE_PHASE_TABLES = {
    "admin_danger_step_ups": "7eb587c877d3ec1ec96f5aaa40308dea8eb93391c21126806010434a9c35ae80",
    "admin_operation_fixtures": "0a67faf5707f4e5bdd0d5ead73829cccef5b67ddc7d8601741445d4a92512747",
    "admin_operations": "c52a622b3267241ab115a4bc33746a205a253ce352beb60e607e436dbd9f6223",
    "admin_rehearsal_sessions": "e242894100290873de651f19acfc0cf1fb56591bd2299725aac0ca06ec43518b",
    "audit_changes": "b6a73a6385da4b21b8b8612e3b6dc7f2e933a621069bf23afa170abbea37663f",
    "audit_events": "8aac8e9125316cb2730b3dceb54afd27dea4b42d050542fc9276bedc9712eacc",
    "corporate_authentication_events": "b939baef6554ea4841ee81fb59a69869e00080456f2b7aa5ed1b0e5b00bba928",
    "corporate_authentication_sessions": "49942daaf00e3b044081fe85144eb094e7caae611edaa4d40a62a0a2a824d61b",
    "corporate_users": "233c830d2e45c8b9a5e78b0ed735ec4d5f58159cea87657c4304be0ca5eec0e7",
    "development_identity_mappings": "0d43d607ea9921acbd73d5e98b7ccee6ead3933bfab5a72bd9833a5350dc1d25",
    "external_group_role_mappings": "848fbb1be3e2831f5ea82d4cf6b39db3f648e88e127a5685a4581a4b1cbaa55a",
}


def _normalized_create_table(connection, table_name: str) -> str:
    row = connection.execute(text(f"SHOW CREATE TABLE {table_name}")).one()
    return re.sub(r"AUTO_INCREMENT=\d+\s+", "", row[1])


def _phase_schema_is_verified_adoption(connection) -> bool:
    """Prove the complete accepted Phase 5 shape before adopting its DDL.

    This handles the accepted divergent production history: its Alembic
    revision is 20260729_0009, but its physical schema already includes the
    accepted Phase 5 objects. Historical revision files remain unchanged;
    Alembic still traverses and records every missing Phase 5 revision. Only
    its already-proven DDL is converted to a no-op, while migration DML runs.
    """
    version_table_exists = connection.execute(
        text(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_schema = DATABASE() AND table_name = 'alembic_version'"
        )
    ).scalar_one()
    if version_table_exists != 1:
        return False
    revisions = {row[0] for row in connection.execute(text("SELECT version_num FROM alembic_version"))}
    if revisions != {_PRODUCTION_HEAD}:
        return False
    for table_name, expected in _ADOPTABLE_PHASE_TABLES.items():
        exists = connection.execute(
            text(
                "SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_schema = DATABASE() AND table_name = :table_name"
            ),
            {"table_name": table_name},
        ).scalar_one()
        if exists != 1:
            return False
        actual = hashlib.sha256(_normalized_create_table(connection, table_name).encode()).hexdigest()
        if actual != expected:
            raise RuntimeError(f"existing {table_name} table is not the accepted compatible Phase 5 shape")
    return True


def _phase_head_has_verified_production_mapping(connection) -> bool:
    """Retain reciprocal Phase-head convergence without relaxing its DDL."""
    version_table_exists = connection.execute(
        text(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_schema = DATABASE() AND table_name = 'alembic_version'"
        )
    ).scalar_one()
    if version_table_exists != 1:
        return False
    revisions = {row[0] for row in connection.execute(text("SELECT version_num FROM alembic_version"))}
    if revisions != {_ADMIN_HEAD}:
        return False
    value = _normalized_create_table(connection, "external_group_role_mappings")
    actual = hashlib.sha256(value.encode()).hexdigest()
    if actual != _ADOPTABLE_PHASE_TABLES["external_group_role_mappings"]:
        raise RuntimeError("existing external group mapping table is not the accepted compatible Phase 5 shape")
    return True


def _install_phase_schema_adoption_guard(connection) -> None:
    """Adopt only pre-verified Phase 5 DDL; retain every migration revision/DML."""
    adopt_full_phase_schema = _phase_schema_is_verified_adoption(connection)
    @event.listens_for(connection, "before_cursor_execute", retval=True)
    def _adopt_existing_phase_schema(_connection, _cursor, statement, parameters, _context, _executemany):
        normalized = statement.lstrip().upper()
        if adopt_full_phase_schema and normalized.startswith(("CREATE TABLE", "CREATE INDEX", "ALTER TABLE")):
            return "SELECT 1 /* verified existing Phase 5 schema adoption */", parameters
        if normalized.startswith("CREATE TABLE EXTERNAL_GROUP_ROLE_MAPPINGS") and _phase_head_has_verified_production_mapping(
            _connection
        ):
            return "SELECT 1 /* verified existing external_group_role_mappings adoption */", parameters
        return statement, parameters


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        render_as_batch=False,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        _install_phase_schema_adoption_guard(connection)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

