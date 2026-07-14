"""Add structured, traceable EOAT history fields.

Revision ID: 20260714_0004
Revises: 20260714_0003
Create Date: 2026-07-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260714_0004"
down_revision: str | None = "20260714_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("entity_history_events", sa.Column("event_uuid", sa.String(36), nullable=True))
    op.add_column("entity_history_events", sa.Column("request_id", sa.String(64)))
    op.add_column("entity_history_events", sa.Column("event_category", sa.String(64), nullable=True))
    op.add_column("entity_history_events", sa.Column("description", sa.Text()))
    op.add_column("entity_history_events", sa.Column("reason", sa.Text()))
    op.add_column("entity_history_events", sa.Column("notes", sa.Text()))
    op.add_column("entity_history_events", sa.Column("previous_values_json", sa.JSON()))
    op.add_column("entity_history_events", sa.Column("new_values_json", sa.JSON()))
    op.add_column("entity_history_events", sa.Column("metadata_json", sa.JSON()))
    op.execute("UPDATE entity_history_events SET event_uuid=UUID() WHERE event_uuid IS NULL")
    op.execute(
        "UPDATE entity_history_events e JOIN history_event_types t ON t.id=e.event_type_id "
        "SET e.event_category=CASE "
        "WHEN t.code IN ('installed','removed','moved_to_storage','location_unknown') THEN 'INSTALLATIONS' "
        "WHEN t.code LIKE 'maintenance_%' THEN 'MAINTENANCE' "
        "WHEN t.code LIKE 'audit_%' THEN 'AUDITS' "
        "WHEN t.code LIKE 'compatibility_%' OR t.code IN ('record_created','record_edited') THEN 'ENGINEERING_CHANGES' "
        "WHEN t.code LIKE 'document_%' OR t.code LIKE 'photo_%' OR t.code='profile_photo_selected' THEN 'DOCUMENTS_AND_PHOTOS' "
        "WHEN t.code LIKE 'tag_%' OR t.code LIKE 'annotation_%' THEN 'TAGS_AND_ANNOTATIONS' "
        "WHEN t.code IN ('record_archived','record_restored') THEN 'ARCHIVE_ACTIVITY' ELSE 'OTHER' END "
        "WHERE e.event_category IS NULL"
    )
    op.alter_column("entity_history_events", "event_uuid", existing_type=sa.String(36), nullable=False)
    op.alter_column("entity_history_events", "event_category", existing_type=sa.String(64), nullable=False)
    op.create_unique_constraint("uq_entity_history_event_uuid", "entity_history_events", ["event_uuid"])
    op.create_index("ix_entity_history_category", "entity_history_events", ["entity_type", "entity_id", "event_category", "occurred_at"])
    op.create_index("ix_entity_history_request", "entity_history_events", ["request_id"])
    op.execute(
        "INSERT IGNORE INTO history_event_types(code,display_name,description,sort_order,is_active) VALUES "
        "('compatibility_created','Compatibility Created','A compatibility relationship was created',155,1),"
        "('compatibility_updated','Compatibility Updated','A compatibility relationship was updated',156,1),"
        "('compatibility_archived','Compatibility Archived','A compatibility relationship was archived',157,1),"
        "('audit_started','Audit Started','An EOAT audit was started',158,1),"
        "('audit_finding_created','Audit Finding Created','An audit finding was recorded',159,1),"
        "('maintenance_started','Maintenance Started','EOAT maintenance was started',160,1),"
        "('document_updated','Document Updated','A linked document was updated',161,1),"
        "('document_archived','Document Archived','A linked document was archived',162,1),"
        "('photo_added','Photo Added','A linked photo was added',163,1),"
        "('photo_updated','Photo Updated','A linked photo was updated',164,1),"
        "('profile_photo_selected','Profile Photo Selected','The EOAT profile photo was selected',165,1),"
        "('photo_archived','Photo Archived','A linked photo was archived',166,1),"
        "('tag_removed','Tag Removed','A tag was removed',167,1),"
        "('annotation_updated','Annotation Updated','An annotation was updated',168,1),"
        "('annotation_archived','Annotation Archived','An annotation was archived',169,1)"
    )
    op.execute(
        "INSERT INTO entity_history_events("
        "event_uuid,entity_type,entity_id,event_type_id,occurred_at,actor_user_id,event_category,summary,notes,"
        "source_table,source_record_id,metadata_json) "
        "SELECT UUID(),'eoat',a.eoat_id,t.id,COALESCE(a.audit_date,a.created_at),a.performed_by_user_id,'AUDITS',"
        "CONCAT('Audit ',a.audit_identifier),a.notes,'audit_records',a.id,"
        "JSON_OBJECT('audit_id',a.audit_identifier,'migration_backfill','20260714_0004') "
        "FROM audit_records a JOIN history_event_types t ON t.code='audit_completed' "
        "WHERE a.eoat_id IS NOT NULL AND NOT EXISTS ("
        "SELECT 1 FROM entity_history_events e WHERE e.entity_type='eoat' AND e.entity_id=a.eoat_id "
        "AND e.source_table='audit_records' AND e.source_record_id=a.id)"
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM entity_history_events WHERE source_table='audit_records' "
        "AND JSON_UNQUOTE(JSON_EXTRACT(metadata_json,'$.migration_backfill'))='20260714_0004'"
    )
    op.execute(
        "DELETE FROM history_event_types WHERE code IN "
        "('compatibility_created','compatibility_updated','compatibility_archived','audit_started',"
        "'audit_finding_created','maintenance_started','document_updated','document_archived','photo_added',"
        "'photo_updated','profile_photo_selected','photo_archived','tag_removed','annotation_updated','annotation_archived')"
    )
    op.drop_index("ix_entity_history_request", table_name="entity_history_events")
    op.drop_index("ix_entity_history_category", table_name="entity_history_events")
    op.drop_constraint("uq_entity_history_event_uuid", "entity_history_events", type_="unique")
    for column in (
        "metadata_json", "new_values_json", "previous_values_json", "notes", "reason", "description",
        "event_category", "request_id", "event_uuid",
    ):
        op.drop_column("entity_history_events", column)
