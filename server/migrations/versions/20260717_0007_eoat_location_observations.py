"""Add honest observation-based EOAT physical-location evidence.

Revision ID: 20260717_0007
Revises: 20260715_0006
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "20260717_0007"
down_revision = "20260715_0006"
branch_labels = None
depends_on = None

PK = mysql.BIGINT(unsigned=True)
STATES = "'INSTALLED','STORED','UNKNOWN','INACTIVE','CONFLICTING'"


def _evidence_columns() -> list[sa.Column]:
    return [
        sa.Column("eoat_id", PK, nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("machine_id", PK, nullable=True),
        sa.Column("storage_location_id", PK, nullable=True),
        # Date-only source evidence is not converted into a fabricated time.
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("observed_on", sa.Date(), nullable=True),
        sa.Column("observation_precision", sa.String(16), nullable=False),
        sa.Column("source_type", sa.String(64), nullable=False),
        sa.Column("source_audit_record_id", PK, nullable=True),
        sa.Column("source_import_row_id", PK, nullable=True),
        sa.Column("source_import_batch_id", PK, nullable=True),
        sa.Column("source_workbook", sa.String(512), nullable=True),
        sa.Column("source_worksheet", sa.String(255), nullable=True),
        sa.Column("source_row_number", sa.Integer(), nullable=True),
        sa.Column("original_source_wording", mysql.MEDIUMTEXT(), nullable=False),
        sa.Column("confidence", sa.String(64), nullable=False),
    ]


def _common_constraints(table: str) -> list[sa.Constraint]:
    return [
        sa.CheckConstraint(f"state IN ({STATES})", name=f"ck_{table}_state"),
        sa.CheckConstraint(
            "(observation_precision = 'TIMESTAMP' AND observed_at IS NOT NULL) OR "
            "(observation_precision = 'DATE' AND observed_at IS NULL AND observed_on IS NOT NULL)",
            name=f"ck_{table}_observation_time",
        ),
        sa.CheckConstraint(
            "(state = 'INSTALLED' AND machine_id IS NOT NULL AND storage_location_id IS NULL) OR "
            "(state = 'STORED' AND machine_id IS NULL) OR "
            "(state IN ('UNKNOWN','INACTIVE','CONFLICTING') AND machine_id IS NULL AND storage_location_id IS NULL)",
            name=f"ck_{table}_physical_target",
        ),
        sa.ForeignKeyConstraint(["eoat_id"], ["eoats.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["machine_id"], ["machines.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["storage_location_id"], ["storage_locations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_audit_record_id"], ["audit_records.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_import_row_id"], ["import_rows.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_import_batch_id"], ["import_batches.id"], ondelete="SET NULL"),
    ]


def upgrade() -> None:
    op.create_table(
        "eoat_location_observations",
        sa.Column("id", PK, autoincrement=True, nullable=False),
        sa.Column("observation_uuid", sa.String(36), nullable=False),
        *_evidence_columns(),
        sa.Column("resolution_status", sa.String(32), nullable=False),
        sa.Column("conflict_group_uuid", sa.String(36), nullable=True),
        sa.Column("is_authoritative", sa.Boolean(), server_default=sa.text("1"), nullable=False),
        sa.Column("superseded_by_observation_id", PK, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("UTC_TIMESTAMP(6)"), nullable=False),
        sa.Column("created_by_user_id", PK, nullable=True),
        sa.Column("row_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("observation_uuid"),
        sa.ForeignKeyConstraint(["superseded_by_observation_id"], ["eoat_location_observations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.CheckConstraint("resolution_status IN ('CURRENT','SUPERSEDED','REVIEW_REQUIRED')", name="ck_eoat_location_observations_resolution"),
        sa.CheckConstraint("row_version > 0", name="ck_eoat_location_observations_row_version"),
        *_common_constraints("eoat_location_observations"),
    )
    op.create_index("ix_eoat_location_observations_current", "eoat_location_observations", ["eoat_id", "is_authoritative", "resolution_status"])
    op.create_index("ix_eoat_location_observations_time", "eoat_location_observations", ["eoat_id", "observed_on", "observed_at"])

    op.create_table(
        "eoat_location_assertions",
        sa.Column("id", PK, autoincrement=True, nullable=False),
        sa.Column("assertion_uuid", sa.String(36), nullable=False),
        sa.Column("observation_id", PK, nullable=False),
        *_evidence_columns(),
        sa.Column("participates_in_conflict", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("UTC_TIMESTAMP(6)"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("assertion_uuid"),
        sa.ForeignKeyConstraint(["observation_id"], ["eoat_location_observations.id"], ondelete="CASCADE"),
        *_common_constraints("eoat_location_assertions"),
    )
    op.create_index("ix_eoat_location_assertions_observation", "eoat_location_assertions", ["observation_id", "source_row_number"])


def downgrade() -> None:
    op.drop_index("ix_eoat_location_assertions_observation", table_name="eoat_location_assertions")
    op.drop_table("eoat_location_assertions")
    op.drop_index("ix_eoat_location_observations_time", table_name="eoat_location_observations")
    op.drop_index("ix_eoat_location_observations_current", table_name="eoat_location_observations")
    op.drop_table("eoat_location_observations")
