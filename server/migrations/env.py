from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, inspect, pool, text

import server.eoat_api.database.models  # noqa: F401
from server.eoat_api.database.base import Base
from server.eoat_api.database.config import migration_database_url

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)
config.set_main_option("sqlalchemy.url", migration_database_url().replace("%", "%%"))
target_metadata = Base.metadata


def _cleanup_uncommitted_data_state(connection) -> None:
    """Remove only the MySQL DDL residue from a failed 0008 upgrade.

    MySQL commits DDL independently of Alembic's transaction wrapper.  The
    canonical 0008 revision creates ``data_state`` before seeding it from
    ``change_feed``; a seed failure would otherwise leave that table behind
    while ``alembic_version`` remains at 0007.  Keep the migration file
    immutable and recover the uniquely identifiable partial state here.
    """
    revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
    inspector = inspect(connection)
    if revision != "20260717_0007" or "data_state" not in inspector.get_table_names():
        return
    expected_columns = {
        "id",
        "current_revision",
        "data_last_modified_at",
        "last_import_at",
        "last_import_source",
        "updated_by",
    }
    if {column["name"] for column in inspector.get_columns("data_state")} != expected_columns:
        return
    checks = {item.get("name") for item in inspector.get_check_constraints("data_state")}
    if "ck_data_state_singleton" not in checks:
        return
    if connection.execute(text("SELECT COUNT(*) FROM data_state")).scalar_one() != 0:
        return
    connection.execute(text("DROP TABLE data_state"))


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
        try:
            with context.begin_transaction():
                context.run_migrations()
        except Exception:
            try:
                _cleanup_uncommitted_data_state(connection)
            except Exception:
                # The migration exception remains the primary diagnostic; an
                # operator must inspect the database before retrying if
                # recovery itself cannot complete.
                pass
            raise


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

