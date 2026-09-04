"""Add governed EOAT onboarding drafts and engineering profile.

Revision ID: 20260904_0018
Revises: 20260828_0017
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "20260904_0018"
down_revision = "20260828_0017"
branch_labels = None
depends_on = None


def _version_columns():
    return [
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False, server_default=sa.text("UTC_TIMESTAMP(6)")),
        sa.Column("updated_at", mysql.DATETIME(fsp=6), nullable=False, server_default=sa.text("UTC_TIMESTAMP(6)")),
        sa.Column("created_by_user_id", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column("updated_by_user_id", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("archived_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("archived_by_user_id", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column("source_system", sa.String(length=64), nullable=False, server_default=sa.text("'eoat_atlas'")),
        sa.Column("source_import_batch_id", mysql.BIGINT(unsigned=True), nullable=True),
    ]


def upgrade() -> None:
    op.create_table(
        "eoat_engineering_profiles",
        sa.Column("id", mysql.BIGINT(unsigned=True), primary_key=True, autoincrement=True),
        sa.Column("eoat_id", mysql.BIGINT(unsigned=True), nullable=False, unique=True),
        sa.Column("cylinders_present", sa.Boolean()), sa.Column("cylinder_count", sa.Integer()),
        sa.Column("cylinder_type", sa.String(length=160)), sa.Column("cylinder_model", sa.String(length=160)),
        sa.Column("gripper_type", sa.String(length=160)), sa.Column("gripper_model", sa.String(length=160)),
        sa.Column("gripper_size", sa.String(length=160)), sa.Column("vacuum_cup_type", sa.String(length=160)),
        sa.Column("vacuum_cup_size", sa.String(length=160)), sa.Column("vacuum_cup_model", sa.String(length=160)),
        sa.Column("vacuum_generation", sa.String(length=255)), sa.Column("vacuum_circuits", sa.Integer()),
        sa.Column("pressure_circuits", sa.Integer()), sa.Column("interchangeable_circuits", sa.Integer()),
        sa.Column("external_circuits", sa.Integer()), sa.Column("pneumatic_connection", sa.String(length=255)),
        sa.Column("pneumatic_notes", sa.Text()), sa.Column("electrical_present", sa.Boolean()),
        sa.Column("electrical_connection", sa.String(length=255)), sa.Column("electrical_pinout_reference", sa.String(length=255)),
        sa.Column("sensor_types", sa.Text()), sa.Column("sensor_models", sa.Text()), *_version_columns(),
        sa.CheckConstraint("cylinder_count IS NULL OR cylinder_count >= 0", name="ck_eoat_engineering_cylinders"),
        sa.ForeignKeyConstraint(["eoat_id"], ["eoats.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["archived_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_import_batch_id"], ["import_batches.id"], ondelete="SET NULL"),
    )
    op.create_table(
        "eoat_onboarding_drafts",
        sa.Column("id", mysql.BIGINT(unsigned=True), primary_key=True, autoincrement=True),
        sa.Column("draft_uuid", sa.String(length=36), nullable=False, unique=True), sa.Column("proposed_identifier", sa.String(length=64)),
        sa.Column("plant_code", sa.String(length=32)), sa.Column("area_code", sa.String(length=64)),
        sa.Column("lifecycle_state", sa.String(length=16), nullable=False, server_default=sa.text("'DRAFT'")),
        sa.Column("completion_state", sa.String(length=32), nullable=False, server_default=sa.text("'INCOMPLETE'")),
        sa.Column("payload_json", sa.JSON(), nullable=False), sa.Column("finalized_eoat_id", mysql.BIGINT(unsigned=True)),
        sa.Column("finalized_at", mysql.DATETIME(fsp=6)), sa.Column("discarded_at", mysql.DATETIME(fsp=6)), sa.Column("discard_reason", sa.Text()), *_version_columns(),
        sa.CheckConstraint("lifecycle_state IN ('DRAFT','FINALIZED','DISCARDED')", name="ck_eoat_onboarding_draft_state"),
        sa.ForeignKeyConstraint(["finalized_eoat_id"], ["eoats.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"), sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["archived_by_user_id"], ["users.id"], ondelete="SET NULL"), sa.ForeignKeyConstraint(["source_import_batch_id"], ["import_batches.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_eoat_onboarding_draft_state_updated", "eoat_onboarding_drafts", ["lifecycle_state", "updated_at"])
    op.create_table(
        "eoat_identifier_reservations", sa.Column("id", mysql.BIGINT(unsigned=True), primary_key=True, autoincrement=True),
        sa.Column("normalized_identifier", sa.String(length=64), nullable=False, unique=True), sa.Column("draft_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("reserved_by_user_id", mysql.BIGINT(unsigned=True)), sa.Column("reserved_at", mysql.DATETIME(fsp=6), nullable=False, server_default=sa.text("UTC_TIMESTAMP(6)")), sa.Column("released_at", mysql.DATETIME(fsp=6)),
        sa.ForeignKeyConstraint(["draft_id"], ["eoat_onboarding_drafts.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["reserved_by_user_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_eoat_identifier_reservation_draft", "eoat_identifier_reservations", ["draft_id"])
    op.create_table(
        "eoat_onboarding_staged_media", sa.Column("id", mysql.BIGINT(unsigned=True), primary_key=True, autoincrement=True),
        sa.Column("draft_id", mysql.BIGINT(unsigned=True), nullable=False), sa.Column("media_kind", sa.String(length=16), nullable=False), sa.Column("document_type", sa.String(length=64), nullable=False),
        sa.Column("file_name", sa.String(length=512), nullable=False), sa.Column("storage_path", sa.String(length=2048), nullable=False), sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text()), sa.Column("revision", sa.String(length=64)), sa.Column("mime_type", sa.String(length=255)), sa.Column("photo_view_type", sa.String(length=64)), sa.Column("caption", sa.Text()), sa.Column("adopted_document_id", mysql.BIGINT(unsigned=True)), *_version_columns(),
        sa.ForeignKeyConstraint(["draft_id"], ["eoat_onboarding_drafts.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["adopted_document_id"], ["documents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"), sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"], ondelete="SET NULL"), sa.ForeignKeyConstraint(["archived_by_user_id"], ["users.id"], ondelete="SET NULL"), sa.ForeignKeyConstraint(["source_import_batch_id"], ["import_batches.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_eoat_onboarding_staged_media_draft", "eoat_onboarding_staged_media", ["draft_id", "is_active"])


def downgrade() -> None:
    op.drop_index("ix_eoat_onboarding_staged_media_draft", table_name="eoat_onboarding_staged_media")
    op.drop_table("eoat_onboarding_staged_media")
    op.drop_index("ix_eoat_identifier_reservation_draft", table_name="eoat_identifier_reservations")
    op.drop_table("eoat_identifier_reservations")
    op.drop_index("ix_eoat_onboarding_draft_state_updated", table_name="eoat_onboarding_drafts")
    op.drop_table("eoat_onboarding_drafts")
    op.drop_table("eoat_engineering_profiles")
