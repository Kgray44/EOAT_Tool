"""Create the Phase 5 server-side corporate group-role mapping store.

Revision ID: 20260813_0009
Revises: 20260813_0008
"""

from __future__ import annotations

from alembic import op

revision = "20260813_0009"
down_revision = "20260813_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The deployed Kerberos-form implementation can already own this exact
    # table while an older accepted lineage still reports revision 0008.  A
    # compatible pre-existing table is therefore adopted, not recreated.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS external_group_role_mappings (
            id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
            provider VARCHAR(32) NOT NULL,
            external_group_identifier VARCHAR(512) NOT NULL,
            role_code VARCHAR(64) NOT NULL,
            explicit_deny BOOL NOT NULL DEFAULT 0,
            is_active BOOL NOT NULL DEFAULT 1,
            created_at DATETIME NOT NULL DEFAULT (UTC_TIMESTAMP(6)),
            updated_at DATETIME NOT NULL DEFAULT (UTC_TIMESTAMP(6)),
            PRIMARY KEY (id),
            CONSTRAINT uq_external_group_role UNIQUE (provider, external_group_identifier, role_code)
        )
        """
    )
    # IT-approved Phase E baseline.  The conditional seed is idempotent and
    # keeps the directory authorization source server-side; it never creates
    # a directory group or changes directory membership.
    op.execute(
        """
        INSERT INTO external_group_role_mappings
            (provider, external_group_identifier, role_code, explicit_deny, is_active)
        SELECT 'kerberos_form',
               'CN=GWP-VT - EOAT Atlas Administrators,OU=GW,DC=gwplastics,DC=com',
               'ADMINISTRATOR', 0, 1
        WHERE NOT EXISTS (
            SELECT 1 FROM external_group_role_mappings
            WHERE provider = 'kerberos_form'
              AND external_group_identifier = 'CN=GWP-VT - EOAT Atlas Administrators,OU=GW,DC=gwplastics,DC=com'
              AND role_code = 'ADMINISTRATOR'
        )
        """
    )


def downgrade() -> None:
    # The table may predate this adopted migration.  Dropping it would erase
    # persisted authorization state, so downgrade is deliberately non-
    # destructive.  A governed cleanup migration can remove only a table it
    # has independently proven to own.
    pass
