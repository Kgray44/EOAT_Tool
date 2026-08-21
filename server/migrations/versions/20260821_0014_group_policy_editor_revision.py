"""Add optimistic concurrency to the existing corporate group-policy store.

Revision ID: 20260821_0014
Revises: 20260820_0013
"""

from alembic import op

revision = "20260821_0014"
down_revision = "20260820_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The converged production-lineage upgrade installs an adoption guard that
    # turns its *historical* CREATE/ALTER statements into no-ops. The marker
    # deliberately keeps this new additive ALTER outside that guard, so the
    # revision can never be recorded without its concurrency column.
    op.execute(
        "/* EOAT_GROUP_POLICY_EDITOR */ "
        "ALTER TABLE external_group_role_mappings "
        "ADD COLUMN row_version INT NOT NULL DEFAULT 1"
    )
    op.execute(
        """
        INSERT IGNORE INTO system_settings
            (setting_key, setting_value_json, value_type, description, is_sensitive, source_system)
        VALUES
            ('app.default_catalog_page_size', '50', 'integer',
             'Default number of Library results shown when a browser has not selected a page size. Individual requests may still choose a supported size.',
             0, 'eoat_atlas')
        """
    )


def downgrade() -> None:
    # The new field is a non-sensitive governance token.  Reversal is safe
    # only after the governed editor is removed from the release line.
    op.execute("/* EOAT_GROUP_POLICY_EDITOR */ " "ALTER TABLE external_group_role_mappings DROP COLUMN row_version")
