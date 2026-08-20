"""Merge the accepted production and Admin/Phase 5 Alembic lineages.

Revision ID: 20260820_0013
Revises: 20260729_0009, 20260820_0012
Create Date: 2026-08-20

The two parents are independently accepted histories that share the
20260714_0004 ancestor.  This successor intentionally performs no schema
mutation: normal Alembic traversal applies the missing branch before recording
the truthful combined head.  Historical parent migrations must remain intact.
"""

from __future__ import annotations

from collections.abc import Sequence

revision: str = "20260820_0013"
down_revision: tuple[str, str] = ("20260729_0009", "20260820_0012")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Record convergence after Alembic has applied the missing branch."""


def downgrade() -> None:
    """Split only the graph topology; parent schema state remains unchanged."""
