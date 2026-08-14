"""Refresh corporate authorization and add scoped fresh-auth metadata.

Revision ID: 20260814_0011
Revises: 20260813_0010
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260814_0011"
down_revision = "20260813_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("corporate_authentication_sessions", sa.Column("authorization_groups_json", sa.JSON(), nullable=True))
    op.add_column("corporate_authentication_sessions", sa.Column("fresh_authenticated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("corporate_authentication_sessions", sa.Column("fresh_auth_operation", sa.String(length=96), nullable=True))
    op.add_column("corporate_authentication_sessions", sa.Column("fresh_auth_risk_class", sa.String(length=32), nullable=True))
    op.add_column("corporate_authentication_sessions", sa.Column("fresh_auth_expires_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("corporate_authentication_sessions", "fresh_auth_expires_at")
    op.drop_column("corporate_authentication_sessions", "fresh_auth_risk_class")
    op.drop_column("corporate_authentication_sessions", "fresh_auth_operation")
    op.drop_column("corporate_authentication_sessions", "fresh_authenticated_at")
    op.drop_column("corporate_authentication_sessions", "authorization_groups_json")
