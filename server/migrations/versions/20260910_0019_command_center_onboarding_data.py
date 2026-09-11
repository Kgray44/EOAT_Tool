"""Retain the complete Command Center onboarding data contract.

Revision ID: 20260910_0019
Revises: 20260904_0018
"""
import sqlalchemy as sa
from alembic import op

revision = "20260910_0019"
down_revision = "20260904_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("eoat_engineering_profiles", sa.Column("command_center_data", sa.JSON(), nullable=True))
    insert_ignore = "INSERT IGNORE" if op.get_bind().dialect.name == "mysql" else "INSERT OR IGNORE"
    op.execute(
        f"{insert_ignore} INTO eoat_types(code,display_name,sort_order,is_active) VALUES "
        "('vacuum','Vacuum',10,1),"
        "('mechanical_gripper','Mechanical / Gripper',20,1),"
        "('hybrid','Hybrid',30,1),"
        "('unknown_needs_review','Unknown / Needs Review',90,1),"
        "('miscellaneous','Miscellaneous',100,1)"
    )
    op.execute(
        f"{insert_ignore} INTO connection_types(code,display_name,sort_order,is_active) VALUES "
        "('ati','ATI',10,1),('dovetail','DoveTail',20,1),"
        "('direct_mount','Direct Mount',30,1),('lever_lock','Lever Lock',40,1)"
    )
    op.execute(
        f"{insert_ignore} INTO cleanroom_classifications(code,display_name,sort_order,is_active) VALUES "
        "('cleanroom','Cleanroom',10,1),('non_cleanroom','Non-Cleanroom',20,1),"
        "('whiteroom','Whiteroom',30,1),('unknown_not_checked','Unknown / Not Checked',90,1)"
    )


def downgrade() -> None:
    # Lookup rows may have existed before this migration or already be used by
    # records; never remove them as part of a schema rollback.
    op.drop_column("eoat_engineering_profiles", "command_center_data")
