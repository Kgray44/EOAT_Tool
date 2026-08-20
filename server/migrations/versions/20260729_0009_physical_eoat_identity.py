"""Add stable physical EOAT identity and source-alias provenance.

Revision ID: 20260729_0009
Revises: 20260721_0008
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "20260729_0009"
down_revision = "20260721_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("eoats", sa.Column("physical_uuid", sa.String(length=36), nullable=True))
    op.add_column("eoats", sa.Column("design_family_identifier", sa.String(length=96), nullable=True))
    op.create_unique_constraint("uq_eoats_physical_uuid", "eoats", ["physical_uuid"])
    op.create_index("ix_eoats_design_family_identifier", "eoats", ["design_family_identifier"], unique=False)
    op.create_table(
        "eoat_identity_aliases",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("eoat_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("alias_identifier", sa.String(length=96), nullable=False),
        sa.Column("alias_type", sa.String(length=32), nullable=False),
        sa.Column("source_row_number", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("owner_decision_reference", sa.String(length=255), nullable=True),
        sa.Column("source_import_batch_id", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False, server_default=sa.text("UTC_TIMESTAMP(6)")),
        sa.ForeignKeyConstraint(["eoat_id"], ["eoats.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_import_batch_id"], ["import_batches.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("eoat_id", "alias_identifier", "alias_type", "source_row_number", name="uq_eoat_identity_alias"),
    )
    op.create_index("ix_eoat_identity_aliases_identifier", "eoat_identity_aliases", ["alias_identifier"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_eoat_identity_aliases_identifier", table_name="eoat_identity_aliases")
    op.drop_table("eoat_identity_aliases")
    op.drop_index("ix_eoats_design_family_identifier", table_name="eoats")
    op.drop_constraint("uq_eoats_physical_uuid", "eoats", type_="unique")
    op.drop_column("eoats", "design_family_identifier")
    op.drop_column("eoats", "physical_uuid")
