"""Register application releases and attach write provenance.

Revision ID: 20260715_0006
Revises: 20260714_0005
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "20260715_0006"
down_revision = "20260714_0005"
branch_labels = None
depends_on = None

PK = mysql.BIGINT(unsigned=True)


def upgrade() -> None:
    op.create_table(
        "application_releases",
        sa.Column("id", PK, autoincrement=True, nullable=False),
        sa.Column("application_version", sa.String(length=64), nullable=False),
        sa.Column("release_id", sa.String(length=128), nullable=False),
        sa.Column("build_id", sa.String(length=255), nullable=False),
        sa.Column("commit_sha", sa.String(length=64), nullable=True),
        sa.Column("release_channel", sa.String(length=64), nullable=False),
        sa.Column("database_schema_revision", sa.String(length=64), nullable=True),
        sa.Column("api_contract_version", sa.String(length=64), nullable=True),
        sa.Column("launcher_version", sa.String(length=64), nullable=True),
        sa.Column("installer_version", sa.String(length=64), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.text("UTC_TIMESTAMP(6)"), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.text("UTC_TIMESTAMP(6)"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("build_id"),
    )
    op.create_index(
        "ix_application_releases_release", "application_releases", ["release_id", "first_seen_at"], unique=False
    )
    op.create_index(
        "ix_application_releases_version",
        "application_releases",
        ["application_version", "first_seen_at"],
        unique=False,
    )

    op.add_column("application_instances", sa.Column("release_id", sa.String(length=128), nullable=True))
    op.add_column("application_instances", sa.Column("build_id", sa.String(length=255), nullable=True))
    _add_release_fk("application_instances")
    _add_release_fk("import_batches")
    _add_release_fk("entity_history_events")
    _add_release_fk("change_audit_log")


def _add_release_fk(table: str) -> None:
    column = "application_release_id"
    op.add_column(table, sa.Column(column, PK, nullable=True))
    op.create_foreign_key(
        f"fk_{table}_application_release",
        table,
        "application_releases",
        [column],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(f"ix_{table}_application_release", table, [column], unique=False)


def downgrade() -> None:
    for table in ("change_audit_log", "entity_history_events", "import_batches", "application_instances"):
        op.drop_index(f"ix_{table}_application_release", table_name=table)
        op.drop_constraint(f"fk_{table}_application_release", table, type_="foreignkey")
        op.drop_column(table, "application_release_id")
    op.drop_column("application_instances", "build_id")
    op.drop_column("application_instances", "release_id")
    op.drop_index("ix_application_releases_version", table_name="application_releases")
    op.drop_index("ix_application_releases_release", table_name="application_releases")
    op.drop_table("application_releases")
