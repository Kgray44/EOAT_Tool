"""Create the Phase 5 server-side corporate group-role mapping store.

Revision ID: 20260813_0009
Revises: 20260813_0008
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "20260813_0009"
down_revision = "20260813_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "external_group_role_mappings",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("external_group_identifier", sa.String(length=512), nullable=False),
        sa.Column("role_code", sa.String(length=64), nullable=False),
        sa.Column("explicit_deny", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("1"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("UTC_TIMESTAMP(6)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("UTC_TIMESTAMP(6)"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "external_group_identifier", "role_code", name="uq_external_group_role"),
    )


def downgrade() -> None:
    op.drop_table("external_group_role_mappings")
