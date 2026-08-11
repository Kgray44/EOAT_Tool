from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from ..database import models as db
from ..security import ActorContext
from .diffing import material_diff
from .redaction import redact
from .taxonomy import (
    AuditAction,
    AuditActorType,
    AuditResult,
    AuditSource,
    action_for_legacy_operation,
    category_for_action,
)


@dataclass(frozen=True)
class AuditWriteResult:
    event_id: str
    changed_fields: list[str]


class AuditEventWriter:
    """The only application writer for committed global audit events."""

    def write_change(
        self,
        session: Session,
        actor: ActorContext,
        *,
        entity_type: str,
        entity_id: int | str,
        entity_display_id: str | None,
        operation: str,
        previous: dict[str, Any] | None,
        current: dict[str, Any] | None,
        reason: str | None = None,
        source: AuditSource = AuditSource.API,
        correlation_id: str | None = None,
        transaction_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        action: AuditAction | None = None,
    ) -> AuditWriteResult:
        diff = material_diff(previous, current)
        controlled_action = action or action_for_legacy_operation(operation)
        event_id = str(uuid4())
        session.add(
            db.AuditEvent(
                event_id=event_id,
                occurred_at_utc=datetime.now(timezone.utc),
                actor_type=AuditActorType.USER.value,
                actor_id=str(actor.user_id),
                actor_display_name=actor.display_name,
                actor_directory_name=actor.identity,
                actor_user_id=actor.user_id,
                action=controlled_action.value,
                action_category=category_for_action(controlled_action).value,
                entity_type=entity_type,
                entity_id=str(entity_id),
                entity_display_id=entity_display_id,
                changed_fields_json=diff.changed_fields,
                before_state_json=diff.before or None,
                after_state_json=diff.after or None,
                reason_or_note=reason,
                source_client=source.value,
                request_id=actor.request_id,
                correlation_id=correlation_id or actor.request_id,
                transaction_id=transaction_id,
                operation=operation,
                result=AuditResult.SUCCESS.value,
                metadata_json=redact(metadata or {}),
                schema_version=1,
            )
        )
        # `audit_changes.audit_event_id` references the event's public UUID,
        # rather than its numeric primary key.  Flush the parent first so
        # MySQL can enforce that foreign key even though the ORM has no
        # relationship dependency to infer the insert order from.
        session.flush()
        for field_path in diff.changed_fields:
            session.add(
                db.AuditChange(
                    audit_event_id=event_id,
                    field_path=field_path,
                    before_value_json=diff.before.get(field_path),
                    after_value_json=diff.after.get(field_path),
                )
            )
        # Flush now: a mandatory-audit failure aborts the caller's existing
        # transaction before any write route can report a successful response.
        session.flush()
        return AuditWriteResult(event_id=event_id, changed_fields=diff.changed_fields)


def execute_with_required_audit(session: Session, mutate, write_audit):
    """Shared savepoint seam for new governed services and rollback tests."""
    with session.begin_nested():
        result = mutate()
        write_audit()
        session.flush()
        return result
