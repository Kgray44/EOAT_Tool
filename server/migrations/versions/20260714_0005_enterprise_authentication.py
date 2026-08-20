"""Enterprise authentication foundation scoped to Settings administration.

Revision ID: 20260714_0005
Revises: 20260714_0004
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "20260714_0005"
down_revision = "20260714_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("external_subject", sa.String(length=255), nullable=True))
    op.add_column("users", sa.Column("first_login_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("last_role_sync_at", sa.DateTime(timezone=True), nullable=True))
    op.create_unique_constraint("uq_users_external_subject", "users", ["external_subject"])

    op.create_table(
        "authentication_sessions",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("session_uuid", sa.String(length=36), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("application_instance_id", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("authentication_method", sa.String(length=64), nullable=False),
        sa.Column("roles_json", sa.JSON(), nullable=False),
        sa.Column("permissions_json", sa.JSON(), nullable=False),
        sa.Column("authenticated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("UTC_TIMESTAMP(6)"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("refreshed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revocation_reason", sa.String(length=128), nullable=True),
        sa.ForeignKeyConstraint(["application_instance_id"], ["application_instances.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_uuid"),
    )
    op.create_index("ix_auth_sessions_token_hash", "authentication_sessions", ["token_hash"], unique=True)
    op.create_index(
        "ix_auth_sessions_user_active",
        "authentication_sessions",
        ["user_id", "revoked_at", "expires_at"],
        unique=False,
    )

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

    op.create_table(
        "authentication_audit_events",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("event_uuid", sa.String(length=36), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.text("UTC_TIMESTAMP(6)"), nullable=False),
        sa.Column("external_subject", sa.String(length=255), nullable=True),
        sa.Column("user_id", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column("application_instance_id", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column("operation", sa.String(length=128), nullable=True),
        sa.Column("result", sa.String(length=32), nullable=False),
        sa.Column("reason_code", sa.String(length=64), nullable=True),
        sa.Column("client_version", sa.String(length=64), nullable=True),
        sa.Column("source_ip", sa.String(length=64), nullable=True),
        sa.Column("details_json", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["application_instance_id"], ["application_instances.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_uuid"),
    )
    op.create_index(
        "ix_auth_audit_occurred_event",
        "authentication_audit_events",
        ["occurred_at", "event_type"],
        unique=False,
    )


def downgrade() -> None:
    # MySQL may select the composite session index to support the user FK;
    # dropping the table lets InnoDB remove indexes and constraints together.
    # IF EXISTS also makes recovery deterministic after interrupted non-
    # transactional DDL in a disposable test database.
    op.execute("DROP TABLE IF EXISTS authentication_audit_events")
    op.execute("DROP TABLE IF EXISTS external_group_role_mappings")
    op.execute("DROP TABLE IF EXISTS authentication_sessions")
    op.drop_constraint("uq_users_external_subject", "users", type_="unique")
    op.drop_column("users", "last_role_sync_at")
    op.drop_column("users", "first_login_at")
    op.drop_column("users", "external_subject")
