from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..database import models as db


class AuditEventRepository:
    def __init__(self, session: Session):
        self.session = session

    def get(self, event_id: str) -> db.AuditEvent | None:
        return self.session.scalar(select(db.AuditEvent).where(db.AuditEvent.event_id == event_id))

    def list(
        self,
        *,
        page: int,
        page_size: int,
        start: datetime | None = None,
        end: datetime | None = None,
        actor: str | None = None,
        action: str | None = None,
        entity_type: str | None = None,
        entity_id: str | None = None,
        result: str | None = None,
        source: str | None = None,
        request_id: str | None = None,
        correlation_id: str | None = None,
        search: str | None = None,
    ) -> tuple[list[db.AuditEvent], int]:
        stmt = select(db.AuditEvent)
        if start:
            stmt = stmt.where(db.AuditEvent.occurred_at_utc >= start)
        if end:
            stmt = stmt.where(db.AuditEvent.occurred_at_utc <= end)
        for column, value in (
            (db.AuditEvent.actor_directory_name, actor),
            (db.AuditEvent.action, action),
            (db.AuditEvent.entity_type, entity_type),
            (db.AuditEvent.entity_id, entity_id),
            (db.AuditEvent.result, result),
            (db.AuditEvent.source_client, source),
            (db.AuditEvent.request_id, request_id),
            (db.AuditEvent.correlation_id, correlation_id),
        ):
            if value:
                stmt = stmt.where(column == value)
        if search:
            needle = f"%{search}%"
            stmt = stmt.where(
                or_(
                    db.AuditEvent.event_id.like(needle),
                    db.AuditEvent.entity_display_id.like(needle),
                    db.AuditEvent.actor_display_name.like(needle),
                    db.AuditEvent.actor_directory_name.like(needle),
                )
            )
        total = self.session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = self.session.scalars(
            stmt.order_by(db.AuditEvent.occurred_at_utc.desc(), db.AuditEvent.event_id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        return rows, total
