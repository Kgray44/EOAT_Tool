"""Add durable Phase 4 operation, step-up, and test-fixture state.

Revision ID: 20260813_0008
Revises: 20260811_0007
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "20260813_0008"
down_revision = "20260811_0007"
branch_labels = None
depends_on = None

PK = mysql.BIGINT(unsigned=True)


def upgrade() -> None:
    op.create_table(
        "admin_danger_step_ups",
        sa.Column("id", PK, primary_key=True, autoincrement=True),
        sa.Column("step_up_reference", sa.String(length=36), nullable=False, unique=True),
        sa.Column("admin_rehearsal_session_id", PK, sa.ForeignKey("admin_rehearsal_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("operation_type", sa.String(length=96), nullable=False),
        sa.Column("risk_class", sa.String(length=32), nullable=False),
        sa.Column("issued_at", sa.DateTime(), server_default=sa.text("UTC_TIMESTAMP(6)"), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_admin_danger_step_ups_session_expiry", "admin_danger_step_ups", ["admin_rehearsal_session_id", "expires_at", "revoked_at"])
    op.create_index("ix_admin_danger_step_ups_scope", "admin_danger_step_ups", ["operation_type", "risk_class", "expires_at"])
    op.create_table(
        "admin_operations",
        sa.Column("id", PK, primary_key=True, autoincrement=True),
        sa.Column("operation_id", sa.String(length=36), nullable=False, unique=True),
        sa.Column("operation_type", sa.String(length=96), nullable=False),
        sa.Column("risk_class", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("actor_user_id", PK, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("target_json", sa.JSON(), nullable=True),
        sa.Column("preview_reference", sa.String(length=36), nullable=True),
        sa.Column("preview_expires_at", sa.DateTime(), nullable=True),
        sa.Column("target_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("lock_key", sa.String(length=128), nullable=True),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("UTC_TIMESTAMP(6)"), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("preview_reference", name="uq_admin_operations_preview_reference"),
    )
    op.create_index("ix_admin_operations_status", "admin_operations", ["operation_type", "status", "created_at"])
    op.create_index("ix_admin_operations_actor", "admin_operations", ["actor_user_id", "created_at"])
    op.create_index("ix_admin_operations_lock", "admin_operations", ["lock_key", "status"])
    op.create_table(
        "admin_operation_fixtures",
        sa.Column("id", PK, primary_key=True, autoincrement=True),
        sa.Column("fixture_namespace", sa.String(length=96), nullable=False),
        sa.Column("fixture_key", sa.String(length=128), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("UTC_TIMESTAMP(6)"), nullable=False),
        sa.UniqueConstraint("fixture_namespace", "fixture_key", name="uq_admin_operation_fixture_namespace_key"),
    )
    op.create_index("ix_admin_operation_fixtures_namespace", "admin_operation_fixtures", ["fixture_namespace"])


def downgrade() -> None:
    op.drop_table("admin_operation_fixtures")
    op.drop_table("admin_operations")
    op.drop_table("admin_danger_step_ups")
