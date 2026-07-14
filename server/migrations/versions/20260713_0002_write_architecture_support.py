"""Add server-first write, annotation, maintenance, and idempotency support.

Revision ID: 20260713_0002
Revises: 20260713_0001
Create Date: 2026-07-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20260713_0002"
down_revision: str | None = "20260713_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PK = mysql.BIGINT(unsigned=True)
UTC_DEFAULT = sa.text("UTC_TIMESTAMP(6)")


def _version_columns() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(), server_default=UTC_DEFAULT, nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=UTC_DEFAULT, nullable=False),
        sa.Column("created_by_user_id", PK, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("updated_by_user_id", PK, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("row_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("1"), nullable=False),
        sa.Column("archived_at", sa.DateTime()),
        sa.Column("archived_by_user_id", PK, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("source_system", sa.String(64), server_default=sa.text("'eoat_atlas'"), nullable=False),
        sa.Column("source_import_batch_id", PK, sa.ForeignKey("import_batches.id", ondelete="SET NULL")),
    ]


def upgrade() -> None:
    op.create_table(
        "tags",
        sa.Column("id", PK, primary_key=True, autoincrement=True),
        sa.Column("tag_code", sa.String(96), nullable=False, unique=True),
        sa.Column("display_name", sa.String(160), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("color_key", sa.String(32), nullable=False),
        sa.Column("is_default", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.Column("source_record_identifier", sa.String(255), unique=True),
        *_version_columns(),
        sa.CheckConstraint("row_version > 0", name="ck_tags_row_version"),
    )
    op.create_index("ix_tags_display_name", "tags", ["display_name"])

    op.create_table(
        "annotation_targets",
        sa.Column("id", PK, primary_key=True, autoincrement=True),
        sa.Column("target_uuid", sa.String(64), nullable=False, unique=True),
        sa.Column("target_type", sa.String(64), nullable=False),
        sa.Column("target_label", sa.String(512)),
        sa.Column("audit_identifier", sa.String(96)),
        sa.Column("machine_identifier", sa.String(96)),
        sa.Column("field_key", sa.String(160)),
        sa.Column("field_label", sa.String(255)),
        sa.Column("sheet_name", sa.String(128)),
        sa.Column("header_name", sa.String(255)),
        sa.Column("workbook_path", sa.String(2048)),
        sa.Column("cached_cell_ref", sa.String(64)),
        sa.Column("object_ref", sa.String(512)),
        sa.Column("source_record_identifier", sa.String(255), unique=True),
        *_version_columns(),
    )
    op.create_index("ix_annotation_targets_type", "annotation_targets", ["target_type"])
    op.create_index("ix_annotation_targets_audit_field", "annotation_targets", ["audit_identifier", "field_key"])

    op.create_table(
        "entity_tags",
        sa.Column("id", PK, primary_key=True, autoincrement=True),
        sa.Column("tag_id", PK, sa.ForeignKey("tags.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("entity_type", sa.String(64), nullable=False),
        sa.Column("entity_id", PK, nullable=False),
        sa.Column("annotation_target_id", PK, sa.ForeignKey("annotation_targets.id", ondelete="RESTRICT")),
        sa.Column("comment", sa.Text()),
        sa.Column("assigned_at", sa.DateTime(), server_default=UTC_DEFAULT, nullable=False),
        sa.Column("assigned_by_user_id", PK, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("removed_at", sa.DateTime()),
        sa.Column("removed_by_user_id", PK, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("row_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("source_record_identifier", sa.String(255), unique=True),
        sa.Column("source_import_batch_id", PK, sa.ForeignKey("import_batches.id", ondelete="SET NULL")),
        sa.Column(
            "active_assignment_key",
            sa.String(255),
            sa.Computed(
                "CASE WHEN removed_at IS NULL THEN CONCAT(tag_id, ':', entity_type, ':', entity_id) ELSE NULL END"
            ),
        ),
        sa.CheckConstraint("row_version > 0", name="ck_entity_tags_row_version"),
        sa.UniqueConstraint("active_assignment_key", name="uq_entity_tags_active_assignment"),
    )
    op.create_index("ix_entity_tags_entity", "entity_tags", ["entity_type", "entity_id"])
    op.create_index("ix_entity_tags_target", "entity_tags", ["annotation_target_id"])

    op.create_table(
        "annotations",
        sa.Column("id", PK, primary_key=True, autoincrement=True),
        sa.Column("annotation_uuid", sa.String(64), nullable=False, unique=True),
        sa.Column("entity_type", sa.String(64)),
        sa.Column("entity_id", PK),
        sa.Column("annotation_target_id", PK, sa.ForeignKey("annotation_targets.id", ondelete="SET NULL")),
        sa.Column("annotation_type", sa.String(64), server_default=sa.text("'note'"), nullable=False),
        sa.Column("subject", sa.String(512), nullable=False),
        sa.Column("body", mysql.MEDIUMTEXT(), nullable=False),
        sa.Column("importance", sa.String(32), server_default=sa.text("'Neutral'"), nullable=False),
        sa.Column("status", sa.String(64)),
        sa.Column("collection", sa.String(160)),
        sa.Column("follow_up_date", sa.Date()),
        sa.Column("source_record_identifier", sa.String(255), unique=True),
        *_version_columns(),
        sa.CheckConstraint("row_version > 0", name="ck_annotations_row_version"),
    )
    op.create_index("ix_annotations_entity", "annotations", ["entity_type", "entity_id"])
    op.create_index("ix_annotations_target", "annotations", ["annotation_target_id"])
    op.create_index("ix_annotations_status", "annotations", ["status"])

    op.create_table(
        "annotation_target_links",
        sa.Column("id", PK, primary_key=True, autoincrement=True),
        sa.Column("annotation_id", PK, sa.ForeignKey("annotations.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "annotation_target_id", PK, sa.ForeignKey("annotation_targets.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(), server_default=UTC_DEFAULT, nullable=False),
        sa.UniqueConstraint("annotation_id", "annotation_target_id", name="uq_annotation_target_links"),
    )

    op.create_table(
        "maintenance_events",
        sa.Column("id", PK, primary_key=True, autoincrement=True),
        sa.Column("event_uuid", sa.String(36), nullable=False, unique=True),
        sa.Column("eoat_id", PK, sa.ForeignKey("eoats.id", ondelete="SET NULL")),
        sa.Column("machine_id", PK, sa.ForeignKey("machines.id", ondelete="SET NULL")),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime()),
        sa.Column("downtime_minutes", sa.Integer()),
        sa.Column("summary", sa.String(512), nullable=False),
        sa.Column("details_json", sa.JSON()),
        sa.Column("application_instance_id", PK, sa.ForeignKey("application_instances.id", ondelete="SET NULL")),
        *_version_columns(),
        sa.CheckConstraint(
            "downtime_minutes IS NULL OR downtime_minutes >= 0", name="ck_maintenance_downtime_nonnegative"
        ),
    )
    op.create_index("ix_maintenance_entity", "maintenance_events", ["eoat_id", "machine_id", "occurred_at"])

    op.create_table(
        "idempotency_records",
        sa.Column("id", PK, primary_key=True, autoincrement=True),
        sa.Column("actor_user_id", PK, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("operation", sa.String(128), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=False),
        sa.Column("response_json", sa.JSON(), nullable=False),
        sa.Column("result_entity_type", sa.String(64)),
        sa.Column("result_entity_id", PK),
        sa.Column("request_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=UTC_DEFAULT, nullable=False),
        sa.Column("expires_at", sa.DateTime()),
        sa.UniqueConstraint(
            "actor_user_id", "operation", "idempotency_key", name="uq_idempotency_actor_operation_key"
        ),
    )
    op.create_index("ix_idempotency_expires", "idempotency_records", ["expires_at"])

    roles = sa.table(
        "roles",
        sa.column("role_code", sa.String),
        sa.column("role_name", sa.String),
        sa.column("description", sa.Text),
        sa.column("is_active", sa.Boolean),
    )
    op.bulk_insert(
        roles,
        [
            {"role_code": "VIEWER", "role_name": "Viewer", "description": "Read-only access", "is_active": True},
            {
                "role_code": "TECHNICIAN",
                "role_name": "Technician",
                "description": "Operational write access",
                "is_active": True,
            },
            {
                "role_code": "ENGINEER",
                "role_name": "Engineer",
                "description": "Engineering write access",
                "is_active": True,
            },
            {
                "role_code": "ADMINISTRATOR",
                "role_name": "Administrator",
                "description": "Controlled administrative access",
                "is_active": True,
            },
        ],
    )
    op.execute(
        "INSERT IGNORE INTO asset_statuses(code,display_name,description,sort_order,is_active) VALUES "
        "('open','Open','Open work record',20,1),"
        "('completed','Completed','Completed work record',30,1),"
        "('archived','Archived','Archived record',90,1)"
    )
    op.execute(
        "INSERT IGNORE INTO compatibility_statuses(code,display_name,description,sort_order,is_active) VALUES "
        "('compatible','Compatible','Verified compatible',10,1),"
        "('incompatible','Incompatible','Verified incompatible',20,1),"
        "('unknown','Unknown','Not yet verified',30,1),"
        "('needs_review','Needs Review','Requires engineering review',40,1)"
    )
    op.execute(
        "INSERT IGNORE INTO compatibility_sources(code,display_name,description,sort_order,is_active) VALUES "
        "('user_verified','User Verified','Verified through an authenticated API write',10,1)"
    )
    op.execute(
        "INSERT IGNORE INTO document_types(code,display_name,description,sort_order,is_active) VALUES "
        "('document','Document','Controlled document metadata',10,1),"
        "('photo','Photo','Controlled photo metadata',20,1)"
    )
    op.execute(
        "INSERT IGNORE INTO history_event_types(code,display_name,description,sort_order,is_active) VALUES "
        "('record_created','Record Created','A user created the record',10,1),"
        "('record_edited','Record Edited','A user edited the record',20,1),"
        "('record_archived','Record Archived','A user archived the record',30,1),"
        "('record_restored','Record Restored','A user restored the record',40,1),"
        "('installed','EOAT Installed','An EOAT was installed',50,1),"
        "('removed','EOAT Removed','An EOAT was removed',60,1),"
        "('moved_to_storage','Moved to Storage','An EOAT was moved to storage',70,1),"
        "('location_unknown','Location Unknown','An EOAT location was explicitly cleared',80,1),"
        "('compatibility_verified','Compatibility Verified','Compatibility was changed',90,1),"
        "('document_added','Document Added','Document metadata was added',100,1),"
        "('document_superseded','Document Superseded','A document was superseded',110,1),"
        "('audit_completed','Audit Completed','An audit was completed',120,1),"
        "('maintenance_completed','Maintenance Completed','Maintenance was completed',130,1),"
        "('tag_assigned','Tag Assigned','A tag was assigned',140,1),"
        "('annotation_added','Annotation Added','An annotation was added',150,1)"
    )


def downgrade() -> None:
    op.execute("DELETE FROM user_roles WHERE role_id IN (SELECT id FROM roles WHERE role_code IN ('VIEWER','TECHNICIAN','ENGINEER','ADMINISTRATOR'))")
    op.execute("DELETE FROM roles WHERE role_code IN ('VIEWER','TECHNICIAN','ENGINEER','ADMINISTRATOR')")
    op.drop_table("idempotency_records")
    op.drop_table("maintenance_events")
    op.drop_table("annotation_target_links")
    op.drop_table("annotations")
    op.drop_table("entity_tags")
    op.drop_table("annotation_targets")
    op.drop_table("tags")
    op.execute(
        "DELETE FROM history_event_types WHERE code IN "
        "('record_created','record_edited','record_archived','record_restored','installed','removed',"
        "'moved_to_storage','location_unknown','compatibility_verified','document_added','document_superseded',"
        "'audit_completed','maintenance_completed','tag_assigned','annotation_added')"
    )
    op.execute("DELETE FROM document_types WHERE code='document'")
    op.execute("DELETE FROM compatibility_sources WHERE code='user_verified'")
    op.execute("DELETE FROM compatibility_statuses WHERE code IN ('compatible','incompatible','unknown','needs_review')")
    op.execute("DELETE FROM asset_statuses WHERE code IN ('open','completed','archived')")
