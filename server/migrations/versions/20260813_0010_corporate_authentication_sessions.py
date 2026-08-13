"""Add opaque Kerberos-form corporate session and audit tables.

Revision ID: 20260813_0010
Revises: 20260813_0009
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "20260813_0010"
down_revision = "20260813_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "corporate_authentication_sessions",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("session_reference", sa.String(length=36), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("csrf_token_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("roles_json", sa.JSON(), nullable=False),
        sa.Column("authenticated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), server_default=sa.text("UTC_TIMESTAMP(6)"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoke_reason", sa.String(length=128), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_reference"),
        sa.UniqueConstraint("token_hash", name="uq_corporate_authentication_session_token"),
    )
    op.create_index("ix_corporate_authentication_sessions_user_active", "corporate_authentication_sessions", ["user_id", "expires_at", "revoked_at"])
    op.create_table(
        "corporate_authentication_events",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("event_uuid", sa.String(length=36), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.text("UTC_TIMESTAMP(6)"), nullable=False),
        sa.Column("result", sa.String(length=32), nullable=False),
        sa.Column("user_id", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=True),
        sa.Column("reason_code", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_uuid"),
    )
    op.create_index("ix_corporate_authentication_events_occurred", "corporate_authentication_events", ["occurred_at", "event_type"])


def downgrade() -> None:
    op.drop_table("corporate_authentication_events")
    op.drop_table("corporate_authentication_sessions")
