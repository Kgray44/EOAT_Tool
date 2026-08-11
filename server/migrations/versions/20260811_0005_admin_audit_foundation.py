"""Add the Phase 1 global administrator audit ledger foundation.

Revision ID: 20260811_0005
Revises: 20260714_0004
Create Date: 2026-08-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20260811_0005"
down_revision: str | None = "20260714_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PK = mysql.BIGINT(unsigned=True)
UTC_DEFAULT = sa.text("UTC_TIMESTAMP(6)")


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column("id", PK, primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.String(36), nullable=False, unique=True),
        sa.Column("occurred_at_utc", sa.DateTime(timezone=True), server_default=UTC_DEFAULT, nullable=False),
        sa.Column("actor_type", sa.String(32), nullable=False),
        sa.Column("actor_id", sa.String(255)),
        sa.Column("actor_display_name", sa.String(255)),
        sa.Column("actor_directory_name", sa.String(255)),
        sa.Column("actor_user_id", PK, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("entity_type", sa.String(64), nullable=False),
        sa.Column("entity_id", sa.String(255), nullable=False),
        sa.Column("entity_display_id", sa.String(255)),
        sa.Column("changed_fields_json", sa.JSON()),
        sa.Column("before_state_json", sa.JSON()),
        sa.Column("after_state_json", sa.JSON()),
        sa.Column("reason_or_note", sa.Text()),
        sa.Column("source_client", sa.String(64), nullable=False),
        sa.Column("request_id", sa.String(64)),
        sa.Column("correlation_id", sa.String(64)),
        sa.Column("transaction_id", sa.String(64)),
        sa.Column("operation", sa.String(255)),
        sa.Column("result", sa.String(16), nullable=False),
        sa.Column("metadata_json", sa.JSON()),
        sa.Column("schema_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=UTC_DEFAULT, nullable=False),
        sa.CheckConstraint(
            "actor_type IN ('user','service','system','import','migration')", name="ck_audit_events_actor_type"
        ),
        sa.CheckConstraint("result IN ('SUCCESS','FAILURE','DENIED','PARTIAL')", name="ck_audit_events_result"),
        sa.CheckConstraint("schema_version > 0", name="ck_audit_events_schema_version"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )
    op.create_index("ix_audit_events_time", "audit_events", ["occurred_at_utc"])
    op.create_index("ix_audit_events_actor_time", "audit_events", ["actor_id", "occurred_at_utc"])
    op.create_index("ix_audit_events_action_time", "audit_events", ["action", "occurred_at_utc"])
    op.create_index("ix_audit_events_entity_time", "audit_events", ["entity_type", "entity_id", "occurred_at_utc"])
    op.create_index("ix_audit_events_result", "audit_events", ["result"])
    op.create_index("ix_audit_events_correlation", "audit_events", ["correlation_id"])
    op.create_index("ix_audit_events_request", "audit_events", ["request_id"])
    op.create_table(
        "audit_changes",
        sa.Column("id", PK, primary_key=True, autoincrement=True),
        sa.Column("audit_event_id", sa.String(36), sa.ForeignKey("audit_events.event_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("field_path", sa.String(512), nullable=False),
        sa.Column("before_value_json", sa.JSON()),
        sa.Column("after_value_json", sa.JSON()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=UTC_DEFAULT, nullable=False),
        sa.UniqueConstraint("audit_event_id", "field_path", name="uq_audit_changes_event_field"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )
    op.create_index("ix_audit_changes_field", "audit_changes", ["field_path"])


def downgrade() -> None:
    op.drop_index("ix_audit_changes_field", table_name="audit_changes")
    op.drop_table("audit_changes")
    for index_name in (
        "ix_audit_events_request",
        "ix_audit_events_correlation",
        "ix_audit_events_result",
        "ix_audit_events_entity_time",
        "ix_audit_events_action_time",
        "ix_audit_events_actor_time",
        "ix_audit_events_time",
    ):
        op.drop_index(index_name, table_name="audit_events")
    op.drop_table("audit_events")
