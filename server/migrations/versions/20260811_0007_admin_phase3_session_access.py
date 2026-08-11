"""Add isolated Phase 3 Admin rehearsal sessions and development role mappings.

Revision ID: 20260811_0007
Revises: 20260811_0006
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "20260811_0007"
down_revision = "20260811_0006"
branch_labels = None
depends_on = None


PK = mysql.BIGINT(unsigned=True)


def upgrade() -> None:
    op.create_table(
        "development_identity_mappings",
        sa.Column("id", PK, primary_key=True, autoincrement=True),
        sa.Column("environment", sa.String(length=32), nullable=False),
        sa.Column("identity", sa.String(length=255), nullable=False),
        sa.Column("role_code", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("UTC_TIMESTAMP(6)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("UTC_TIMESTAMP(6)"), nullable=False),
        sa.Column("created_by_user_id", PK, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("updated_by_user_id", PK, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("row_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("1"), nullable=False),
        sa.Column("archived_at", sa.DateTime(), nullable=True),
        sa.Column("archived_by_user_id", PK, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("source_system", sa.String(length=64), server_default=sa.text("'eoat_atlas'"), nullable=False),
        sa.Column("source_import_batch_id", PK, sa.ForeignKey("import_batches.id", ondelete="SET NULL"), nullable=True),
        sa.UniqueConstraint("environment", "identity", name="uq_dev_identity_mapping_environment_identity"),
        sa.CheckConstraint("row_version > 0", name="ck_dev_identity_mapping_row_version"),
    )
    op.create_table(
        "admin_rehearsal_sessions",
        sa.Column("id", PK, primary_key=True, autoincrement=True),
        sa.Column("session_reference", sa.String(length=36), nullable=False, unique=True),
        sa.Column("session_token_hash", sa.String(length=64), nullable=False),
        sa.Column("csrf_token_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", PK, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("environment", sa.String(length=32), nullable=False),
        sa.Column("issued_at", sa.DateTime(), server_default=sa.text("UTC_TIMESTAMP(6)"), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_by_user_id", PK, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("revoke_reason", sa.String(length=512), nullable=True),
        sa.UniqueConstraint("session_token_hash", name="uq_admin_rehearsal_session_token_hash"),
    )
    op.create_index("ix_admin_rehearsal_sessions_user_active", "admin_rehearsal_sessions", ["user_id", "expires_at", "revoked_at"])
    op.create_index("ix_admin_rehearsal_sessions_environment", "admin_rehearsal_sessions", ["environment", "expires_at"])
    op.execute(
        "INSERT IGNORE INTO roles(role_code, role_name, description, is_active) VALUES "
        "('ADMIN_AUDITOR','Administrator Auditor','Read-only Administrator investigation role',1),"
        "('ADMIN_DATA_MANAGER','Administrator Data Manager','Governed data editing role',1),"
        "('ADMIN_SETTINGS_MANAGER','Administrator Settings Manager','Governed settings role',1),"
        "('ADMIN_ACCESS_MANAGER','Administrator Access Manager','Governed local access role',1)"
    )
    op.execute(
        "INSERT IGNORE INTO development_identity_mappings(environment, identity, role_code) VALUES "
        "('development','dev.viewer','VIEWER'),('development','dev.technician','TECHNICIAN'),"
        "('development','dev.engineer','ENGINEER'),('development','dev.admin','ADMINISTRATOR'),"
        "('staging_local','staging.viewer','VIEWER'),('staging_local','staging.technician','TECHNICIAN'),"
        "('staging_local','staging.engineer','ENGINEER'),('staging_local','staging.admin','ADMINISTRATOR')"
    )


def downgrade() -> None:
    # MySQL uses the user-active composite index to support the user_id foreign
    # key.  Dropping the table removes dependent indexes safely; attempting to
    # drop either index first fails with error 1553.
    op.drop_table("admin_rehearsal_sessions")
    op.drop_table("development_identity_mappings")
    op.execute("DELETE FROM roles WHERE role_code IN ('ADMIN_AUDITOR','ADMIN_DATA_MANAGER','ADMIN_SETTINGS_MANAGER','ADMIN_ACCESS_MANAGER')")
