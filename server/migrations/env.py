from __future__ import annotations

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

_ADMIN_HEAD = "20260820_0012"
_PRODUCTION_HEAD = "20260729_0009"
_MAPPING_TABLE = "external_group_role_mappings"
_MAPPING_COLUMNS = {
    "id": ("bigint unsigned", "NO"),
    "provider": ("varchar(32)", "NO"),
    "external_group_identifier": ("varchar(512)", "NO"),
    "role_code": ("varchar(64)", "NO"),
    "explicit_deny": ("tinyint(1)", "NO"),
    "is_active": ("tinyint(1)", "NO"),
    "created_at": ("datetime", "NO"),
    "updated_at": ("datetime", "NO"),
}


def _phase_branch_previously_created_mapping(connection) -> bool:
    """Prove that only the known compatible historical DDL may be adopted.

    Production migration 20260714_0005 predates the Phase 5 branch and uses
    an unconditional create for this table.  Phase 5 migration 20260813_0009
    later created the same accepted shape conditionally.  A database already
    at the Phase 5 head therefore needs the older operation to be a verified
    no-op while its missing production branch is traversed toward the merge.
    """
    version_table_exists = connection.execute(
        text(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_schema = DATABASE() AND table_name = 'alembic_version'"
        )
    ).scalar_one()
    if version_table_exists != 1:
        return False
    revisions = {
        row[0]
        for row in connection.execute(text("SELECT version_num FROM alembic_version"))
    }
    if _ADMIN_HEAD not in revisions or _PRODUCTION_HEAD in revisions:
        return False
    rows = connection.execute(
        text(
            "SELECT column_name, column_type, is_nullable "
            "FROM information_schema.columns "
            "WHERE table_schema = DATABASE() AND table_name = :table_name"
        ),
        {"table_name": _MAPPING_TABLE},
    )
    columns = {row[0]: (row[1].lower(), row[2]) for row in rows}
    if columns != _MAPPING_COLUMNS:
        raise RuntimeError("existing external group mapping table is not the accepted compatible shape")
    index_rows = connection.execute(
        text(
            "SELECT column_name FROM information_schema.statistics "
            "WHERE table_schema = DATABASE() AND table_name = :table_name "
            "AND index_name = 'uq_external_group_role' ORDER BY seq_in_index"
        ),
        {"table_name": _MAPPING_TABLE},
    )
    return [row[0] for row in index_rows] == [
        "provider",
        "external_group_identifier",
        "role_code",
    ]


def _install_phase_mapping_adoption_guard(connection) -> None:
    """Skip only the proven-equivalent historical create during reconciliation."""
    create_prefix = "CREATE TABLE external_group_role_mappings".upper()

    @event.listens_for(connection, "before_cursor_execute", retval=True)
    def _adopt_existing_mapping(_connection, _cursor, statement, parameters, _context, _executemany):
        if statement.lstrip().upper().startswith(create_prefix) and _phase_branch_previously_created_mapping(connection):
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
        _install_phase_mapping_adoption_guard(connection)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

