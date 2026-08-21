from __future__ import annotations

import hashlib
import re
from logging.config import fileConfig

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
_PRODUCTION_LINEAGE = {
    "20260714_0005",
    "20260715_0006",
    "20260717_0007",
    "20260721_0008",
    _PRODUCTION_HEAD,
}
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
_ADOPTABLE_PRODUCTION_TABLES = {
    "users": "edb7355928e8a72f3a2f4ba80abf92bd8613b71b991fd4ebc2c20b03906f68e5",
    "authentication_sessions": "1ba03acc377f3cc822cac3e238f188740044a90a57166e3537f0a15ce1dc8e49",
    "authentication_audit_events": "b5e5dc337145ee441fbda3926a15c5f172f496ca69e001131f4e62521b8ac56e",
    "application_releases": "594ee8f1788362a34f40b311feb1d3954ae7a4698dbfd710346e08e8327c7a12",
    "application_instances": "6c7fc02ad8cd1d3ca731e0b6212b58736265446a0e87e3375fc3acf6446fcfe9",
    "import_batches": "f35be962bb3405e87d78f7fcb440b7794616d8a5c97a15f661286314f5fa19ad",
    "entity_history_events": "c7ef62b67b91547b71a2c0551718e1190c10040b441a324c294f76c7da0d88af",
    "change_audit_log": "ba0b6e438ab116801eb465937335d04c73b3773a6ce9f76c4421b32a4df4d9c5",
    "eoat_location_observations": "cb9c338316fd4efe5be906eccfdadf88af7224e02cdab15da9284504001f3d28",
    "eoat_location_assertions": "7df40125a325e03b97a8b732d89134d524a5ca9ec11fa7dc65f69206530d9eb8",
    "data_state": "09a7dc2df7c8599a10f7dfc21ef7eab3fbdf1ed7d88f3cb425621430f819907f",
    "eoats": "f88a97714200f1537a3c1e2e7165328677516fe3f1a75accb89b889749529aa1",
    "eoat_identity_aliases": "bf13db4333a6f377098e294f374bda2e3d13d67cbe29dd7bb90090444d5d6803",
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
    # A schema accepted at either predecessor of the merge may already carry
    # the complete Phase 5 physical shape.  Both cases still require every
    # table fingerprint below; accepting an arbitrary partially-upgraded
    # version table would risk recording historical revisions without proof.
    verified_predecessor = revisions == {_PRODUCTION_HEAD} or (
        _ADMIN_HEAD in revisions and revisions <= {_ADMIN_HEAD, *_PRODUCTION_LINEAGE}
    )
    if not verified_predecessor:
        return False
    # The full historical production and Phase 5 surfaces must match before
    # any historic DDL can be adopted.  New migrations intentionally do not
    # appear here, so an additive candidate DDL statement cannot be hidden.
    for table_name, expected in {**_ADOPTABLE_PRODUCTION_TABLES, **_ADOPTABLE_PHASE_TABLES}.items():
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


def _group_mapping_was_created_on_the_other_merged_lineage(connection) -> bool:
    """Permit only the duplicate historic CREATE in a fresh merge traversal.

    20260813_0009 created this exact table before the later merge traverses
    20260714_0005. Newer migration DDL is intentionally not included here.
    """
    revisions = {row[0] for row in connection.execute(text("SELECT version_num FROM alembic_version"))}
    # Alembic stores the branch head, not every ancestor.  0012 is the only
    # valid Admin-lineage head at this point and therefore entails 0009.
    if revisions != {_ADMIN_HEAD}:
        return False
    required_columns = {
        "id",
        "provider",
        "external_group_identifier",
        "role_code",
        "explicit_deny",
        "is_active",
        "created_at",
        "updated_at",
    }
    columns = {
        row[0]
        for row in connection.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = DATABASE() AND table_name = 'external_group_role_mappings'"
            )
        )
    }
    unique_constraint = connection.execute(
        text(
            "SELECT COUNT(*) FROM information_schema.table_constraints "
            "WHERE table_schema = DATABASE() AND table_name = 'external_group_role_mappings' "
            "AND constraint_name = 'uq_external_group_role' AND constraint_type = 'UNIQUE'"
        )
    ).scalar_one()
    return required_columns.issubset(columns) and unique_constraint == 1


def _install_phase_schema_adoption_guard(connection) -> None:
    """Adopt only pre-verified Phase 5 DDL; retain every migration revision/DML."""
    adopt_full_phase_schema = _phase_schema_is_verified_adoption(connection)
    @event.listens_for(connection, "before_cursor_execute", retval=True)
    def _adopt_existing_phase_schema(_connection, _cursor, statement, parameters, _context, _executemany):
        normalized = statement.lstrip().upper()
        if adopt_full_phase_schema and normalized.startswith(("CREATE ", "ALTER TABLE")):
            return "SELECT 1 /* verified existing Phase 5 schema adoption */", parameters
        if normalized.startswith("CREATE TABLE EXTERNAL_GROUP_ROLE_MAPPINGS") and _group_mapping_was_created_on_the_other_merged_lineage(
            _connection
        ):
            return "SELECT 1 /* duplicate historical group mapping create after 0009 */", parameters
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

