"""Add EOAT-owned explicit group-policy assignments.

Revision ID: 20260828_0017
Revises: 20260827_0016
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "20260828_0017"
down_revision = "20260827_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A nullable FK gives each corporate user at most one current explicit
    # assignment without pretending EOAT controls directory membership.
    op.add_column(
        "corporate_users",
        sa.Column("explicit_group_policy_id", mysql.BIGINT(unsigned=True), nullable=True),
    )
    op.add_column("corporate_users", sa.Column("policy_assigned_at", sa.DateTime(), nullable=True))
    op.add_column(
        "corporate_users",
        sa.Column("policy_assigned_by_user_id", mysql.BIGINT(unsigned=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_corporate_users_explicit_group_policy",
        "corporate_users",
        "external_group_role_mappings",
        ["explicit_group_policy_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_corporate_users_policy_assigned_by",
        "corporate_users",
        "users",
        ["policy_assigned_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_corporate_users_explicit_policy", "corporate_users", ["explicit_group_policy_id"])


def downgrade() -> None:
    op.drop_index("ix_corporate_users_explicit_policy", table_name="corporate_users")
    op.drop_constraint("fk_corporate_users_policy_assigned_by", "corporate_users", type_="foreignkey")
    op.drop_constraint("fk_corporate_users_explicit_group_policy", "corporate_users", type_="foreignkey")
    op.drop_column("corporate_users", "policy_assigned_by_user_id")
    op.drop_column("corporate_users", "policy_assigned_at")
    op.drop_column("corporate_users", "explicit_group_policy_id")
