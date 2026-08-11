"""Add controlled action-category query dimension to the audit ledger.

Revision ID: 20260811_0006
Revises: 20260811_0005
Create Date: 2026-08-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260811_0006"
down_revision: str | None = "20260811_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "audit_events",
        sa.Column("action_category", sa.String(64), server_default=sa.text("'OTHER'"), nullable=False),
    )
    op.execute(
        "UPDATE audit_events SET action_category=CASE "
        "WHEN action IN ('CREATE','UPDATE','ARCHIVE','RESTORE','DELETE') THEN 'BUSINESS_DATA' "
        "WHEN action IN ('LINK','UNLINK','ASSIGN','UNASSIGN') THEN 'RELATIONSHIPS' "
        "WHEN action IN ('LOCATION_CHANGE','STATUS_CHANGE') THEN 'LOCATION_STATE' "
        "WHEN action IN ('UPLOAD','METADATA_CHANGE','SUPERSEDE','PHOTO_ADD','PHOTO_ARCHIVE') THEN 'DOCUMENTS_MEDIA' "
        "WHEN action IN ('PM_COMPLETE','INSPECTION_COMPLETE') THEN 'MAINTENANCE_INSPECTION' "
        "WHEN action IN ('IMPORT_COMMIT','BULK_OPERATION','CORRECTION') THEN 'IMPORTS_BULK' "
        "WHEN action IN ('LOGIN_SUCCESS','LOGIN_FAILURE','LOGOUT') THEN 'AUTHENTICATION' "
        "WHEN action IN ('ACCESS_DENIED','ROLE_MAPPING_CHANGE','GROUP_MAPPING_CHANGE') THEN 'AUTHORIZATION' "
        "WHEN action='SETTINGS_CHANGE' THEN 'SETTINGS' WHEN action='EXPORT' THEN 'EXPORTS' "
        "WHEN action IN ('SCHEMA_MIGRATED','ADMIN_REPAIR') THEN 'SYSTEM_OPERATIONS' "
        "WHEN action IN ('DANGER_ATTEMPT','DANGER_CONFIRMED','DANGER_STARTED','DANGER_SUCCEEDED','DANGER_FAILED') THEN 'DANGER_ZONE' "
        "ELSE 'OTHER' END"
    )
    op.create_check_constraint("ck_audit_events_action_category", "audit_events", "action_category <> ''")
    op.create_index("ix_audit_events_category_time", "audit_events", ["action_category", "occurred_at_utc"])


def downgrade() -> None:
    op.drop_index("ix_audit_events_category_time", table_name="audit_events")
    op.drop_constraint("ck_audit_events_action_category", "audit_events", type_="check")
    op.drop_column("audit_events", "action_category")
