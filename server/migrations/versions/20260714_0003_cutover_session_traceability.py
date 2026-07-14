"""Add cutover-session traceability.

Revision ID: 20260714_0003
Revises: 20260713_0002
Create Date: 2026-07-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20260714_0003"
down_revision: str | None = "20260713_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PK = mysql.BIGINT(unsigned=True)
UTC_DEFAULT = sa.text("UTC_TIMESTAMP(6)")


def upgrade() -> None:
    op.create_table(
        "cutover_sessions",
        sa.Column("id", PK, primary_key=True, autoincrement=True),
        sa.Column("cutover_uuid", sa.String(36), nullable=False, unique=True),
        sa.Column("environment", sa.String(64), nullable=False),
        sa.Column("source_checksum", sa.String(64), nullable=False),
        sa.Column("source_snapshot_timestamp", sa.DateTime(), nullable=False),
        sa.Column("database_schema_revision", sa.String(64), nullable=False),
        sa.Column("api_version", sa.String(32), nullable=False),
        sa.Column("client_version", sa.String(64), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime()),
        sa.Column("started_by_user_id", PK, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("authority_enabled_at", sa.DateTime()),
        sa.Column("rollback_deadline", sa.DateTime()),
        sa.Column("rollback_started_at", sa.DateTime()),
        sa.Column("rollback_completed_at", sa.DateTime()),
        sa.Column("start_change_feed_cursor", PK, server_default=sa.text("0"), nullable=False),
        sa.Column("notes", sa.Text()),
        sa.Column("created_at", sa.DateTime(), server_default=UTC_DEFAULT, nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=UTC_DEFAULT, nullable=False),
        sa.Column("created_by_user_id", PK, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("updated_by_user_id", PK, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("row_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("1"), nullable=False),
        sa.Column("archived_at", sa.DateTime()),
        sa.Column("archived_by_user_id", PK, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("source_system", sa.String(64), server_default=sa.text("'eoat_atlas'"), nullable=False),
        sa.Column("source_import_batch_id", PK, sa.ForeignKey("import_batches.id", ondelete="SET NULL")),
        sa.CheckConstraint("row_version > 0", name="ck_cutover_sessions_row_version"),
        sa.CheckConstraint(
            "status IN ('PLANNED','SOURCE_FROZEN','IMPORTING','VALIDATING','READY',"
            "'AUTHORITY_ENABLED','MONITORING','ROLLED_BACK','COMPLETED','FAILED','CANCELLED')",
            name="ck_cutover_sessions_status",
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
    )
    op.create_index(
        "ix_cutover_sessions_environment_status",
        "cutover_sessions",
        ["environment", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_cutover_sessions_environment_status", table_name="cutover_sessions")
    op.drop_table("cutover_sessions")
