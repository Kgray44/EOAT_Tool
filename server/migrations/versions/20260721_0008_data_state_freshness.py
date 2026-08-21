"""Add the authoritative EOAT application-data revision singleton.

Revision ID: 20260721_0008
Revises: 20260717_0007
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "20260721_0008"
down_revision = "20260717_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "data_state",
        # MySQL would otherwise infer AUTO_INCREMENT for this integer primary
        # key.  That is incompatible with the singleton check constraint and
        # could also manufacture a second identity outside the seeded row.
        sa.Column("id", sa.SmallInteger(), nullable=False, autoincrement=False),
        sa.Column("current_revision", mysql.BIGINT(unsigned=True), nullable=False, server_default=sa.text("0")),
        sa.Column("data_last_modified_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("last_import_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("last_import_source", sa.String(length=255), nullable=True),
        sa.Column("updated_by", sa.String(length=255), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("id = 1", name="ck_data_state_singleton"),
    )
    # Existing change-feed timestamps are the best available evidence of prior
    # operational changes.  If no feed exists, initialization time is used;
    # that fact is documented rather than presented as historic precision.
    op.execute(
        "INSERT INTO data_state (id, current_revision, data_last_modified_at) "
        "SELECT 1, COALESCE(MAX(change_id), 0), COALESCE(MAX(changed_at), UTC_TIMESTAMP(6)) "
        "FROM change_feed ON DUPLICATE KEY UPDATE id = data_state.id"
    )


def downgrade() -> None:
    op.drop_table("data_state")
