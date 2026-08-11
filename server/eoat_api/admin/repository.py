from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..database import models as db
from .taxonomy import ADMINISTRATIVE_AUDIT_CATEGORIES


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
        action_category: str | None = None,
        security_events_only: bool = False,
        administrative_events_only: bool = False,
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
        if actor:
            stmt = stmt.where(
                or_(
                    db.AuditEvent.actor_directory_name == actor,
                    db.AuditEvent.actor_id == actor,
                    db.AuditEvent.actor_display_name == actor,
                )
            )
        for column, value in (
            (db.AuditEvent.action, action),
            (db.AuditEvent.action_category, action_category),
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
                    db.AuditEvent.actor_id.like(needle),
                    db.AuditEvent.action.like(needle),
                    db.AuditEvent.request_id.like(needle),
                    db.AuditEvent.correlation_id.like(needle),
                    db.AuditEvent.reason_or_note.like(needle),
                )
            )
        if security_events_only:
            stmt = stmt.where(db.AuditEvent.action_category.in_(("AUTHENTICATION", "AUTHORIZATION")))
        if administrative_events_only:
            stmt = stmt.where(db.AuditEvent.action_category.in_(ADMINISTRATIVE_AUDIT_CATEGORIES))
        total = self.session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = self.session.scalars(
            stmt.order_by(db.AuditEvent.occurred_at_utc.desc(), db.AuditEvent.event_id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        return rows, total

    def overview(self, *, now: datetime, recent_limit: int = 8) -> tuple[dict[str, int], list[db.AuditEvent]]:
        """Return bounded, server-derived Admin overview facts.

        UTC is deliberate: it is the persisted source-of-truth timestamp and
        avoids falsely presenting browser-local date boundaries as server facts.
        """
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        else:
            now = now.astimezone(timezone.utc)
        last_24_hours = now - timedelta(hours=24)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        recent = self.session.scalars(
            select(db.AuditEvent)
            .order_by(db.AuditEvent.occurred_at_utc.desc(), db.AuditEvent.event_id.desc())
            .limit(recent_limit)
        ).all()

        def count(*criteria) -> int:
            return self.session.scalar(select(func.count(db.AuditEvent.id)).where(*criteria)) or 0

        window = db.AuditEvent.occurred_at_utc >= last_24_hours
        metrics = {
            "events_today": count(db.AuditEvent.occurred_at_utc >= today_start),
            "events_last_24_hours": count(window),
            "successful_events_last_24_hours": count(window, db.AuditEvent.result == "SUCCESS"),
            "failed_events_last_24_hours": count(window, db.AuditEvent.result == "FAILURE"),
            "denied_events_last_24_hours": count(window, db.AuditEvent.result == "DENIED"),
            "security_events_last_24_hours": count(
                window, db.AuditEvent.action_category.in_(("AUTHENTICATION", "AUTHORIZATION"))
            ),
            "administrative_events_last_24_hours": count(
                window,
                db.AuditEvent.action_category.in_(ADMINISTRATIVE_AUDIT_CATEGORIES),
            ),
            "unique_actors_last_24_hours": self.session.scalar(
                select(func.count(func.distinct(db.AuditEvent.actor_id))).where(
                    window, db.AuditEvent.actor_id.is_not(None)
                )
            )
            or 0,
        }
        return metrics, recent
