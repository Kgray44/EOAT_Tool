"""Add default-deny operational grants to corporate group policies.

Revision ID: 20260827_0016
Revises: 20260821_0015
"""

from alembic import op

revision = "20260827_0016"
down_revision = "20260821_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing mappings receive an empty JSON array: this migration does not
    # grant a single new persistent capability.
    op.execute(
        "ALTER TABLE external_group_role_mappings "
        "ADD COLUMN permissions_json JSON NOT NULL DEFAULT (JSON_ARRAY())"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE external_group_role_mappings DROP COLUMN permissions_json")
