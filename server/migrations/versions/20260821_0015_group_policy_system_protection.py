"""Persist the protected Administrator recovery-policy marker.

Revision ID: 20260821_0015
Revises: 20260821_0014
"""

from alembic import op

revision = "20260821_0015"
down_revision = "20260821_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE external_group_role_mappings "
        "ADD COLUMN is_system_policy TINYINT(1) NOT NULL DEFAULT 0"
    )
    # This is the seeded corporate recovery mapping from 20260813_0009.  The
    # server also recognizes that canonical tuple as a defence in depth check.
    op.execute(
        "UPDATE external_group_role_mappings "
        "SET is_system_policy = 1 "
        "WHERE provider = 'kerberos_form' "
        "AND external_group_identifier = 'CN=GWP-VT - EOAT Atlas Administrators,OU=GW,DC=gwplastics,DC=com' "
        "AND role_code = 'ADMINISTRATOR' AND explicit_deny = 0"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE external_group_role_mappings DROP COLUMN is_system_policy")
