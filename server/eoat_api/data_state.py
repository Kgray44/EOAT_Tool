"""Transaction-scoped authoritative EOAT data freshness metadata.

Write services mark a SQLAlchemy unit of work as user-visible-data changing.
The single ``before_commit`` hook advances the revision once, under a row lock,
in the same transaction as that work.  A rollback therefore cannot publish a
new revision or modification timestamp.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import event, select
from sqlalchemy.orm import Session

from .database import models as db

if TYPE_CHECKING:
    from .security import ActorContext


_DIRTY_KEY = "eoat_data_state_dirty"
_ACTOR_KEY = "eoat_data_state_actor"
_IMPORT_KEY = "eoat_data_state_import"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def mark_data_changed(session: Session, actor: ActorContext | None = None) -> None:
    """Mark the current transaction as changing tracked EOAT application data."""
    session.info[_DIRTY_KEY] = True
    if actor is not None:
        session.info[_ACTOR_KEY] = actor


def record_import_completion(
    session: Session,
    *,
    source: str,
    changed_data: bool,
    actor: ActorContext | None = None,
) -> None:
    """Record a completed import; only a material import advances revision."""
    session.info[_IMPORT_KEY] = {"source": str(source or "")[:255], "at": utcnow()}
    if changed_data:
        mark_data_changed(session, actor)


def current_data_state(session: Session, *, lock: bool = False) -> db.DataState:
    statement = select(db.DataState).where(db.DataState.id == 1)
    if lock:
        statement = statement.with_for_update()
    state = session.scalar(statement)
    if state is None:
        # Migrations seed this row.  Keeping this fallback makes a partially
        # initialized development database recoverable without fabricating an
        # old date: its initialization time is explicitly the first known time.
        state = db.DataState(id=1, current_revision=0, data_last_modified_at=utcnow())
        session.add(state)
        session.flush()
        if lock:
            state = session.scalar(select(db.DataState).where(db.DataState.id == 1).with_for_update()) or state
    return state


@event.listens_for(Session, "before_commit")
def _advance_data_state_before_commit(session: Session) -> None:
    dirty = bool(session.info.pop(_DIRTY_KEY, False))
    import_info = session.info.pop(_IMPORT_KEY, None)
    actor = session.info.pop(_ACTOR_KEY, None)
    if not dirty and not import_info:
        return
    state = current_data_state(session, lock=True)
    if import_info:
        state.last_import_at = import_info["at"]
        state.last_import_source = import_info["source"] or None
    if dirty:
        state.current_revision = int(state.current_revision) + 1
        state.data_last_modified_at = utcnow()
        identity = getattr(actor, "identity", "") if actor is not None else ""
        state.updated_by = str(identity or "EOAT Atlas API")[:255]


__all__ = ["current_data_state", "mark_data_changed", "record_import_completion", "utcnow"]
