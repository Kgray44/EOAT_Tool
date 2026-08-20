"""Add the governed corporate-user registry and explicit access state.

Revision ID: 20260820_0012
Revises: 20260814_0011
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "20260820_0012"
down_revision = "20260814_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "corporate_users",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("user_uuid", sa.String(length=36), nullable=False),
        sa.Column("user_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("canonical_identity", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=160), nullable=False),
        sa.Column("first_successful_sign_in_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_successful_sign_in_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sign_in_count", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("explicit_role_code", sa.String(length=64), nullable=True),
        sa.Column("explicit_denied", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.Column("access_reason", sa.Text(), nullable=True),
        sa.Column("access_changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("access_changed_by_user_id", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column("created_by_user_id", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column("updated_by_user_id", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column("row_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("1"), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_by_user_id", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column("source_system", sa.String(length=64), server_default=sa.text("'corporate_auth'"), nullable=False),
        sa.Column("source_import_batch_id", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("UTC_TIMESTAMP(6)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("UTC_TIMESTAMP(6)"), nullable=False),
        sa.CheckConstraint("sign_in_count >= 1", name="ck_corporate_users_sign_in_count"),
        sa.CheckConstraint("row_version > 0", name="ck_corporate_users_row_version"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["access_changed_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["archived_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_import_batch_id"], ["import_batches.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_uuid"),
        sa.UniqueConstraint("user_id", name="uq_corporate_users_user"),
        sa.UniqueConstraint("provider", "canonical_identity", name="uq_corporate_users_provider_identity"),
    )
    op.create_index("ix_corporate_users_last_sign_in", "corporate_users", ["last_successful_sign_in_at"])
    op.create_index("ix_corporate_users_access", "corporate_users", ["explicit_role_code", "explicit_denied", "is_active"])


def downgrade() -> None:
    op.drop_table("corporate_users")
