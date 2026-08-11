from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class LegacyHistoryEvidence:
    """A display-only legacy representation; it never invents absent facts."""

    legacy_event_id: str
    occurred_at_utc: datetime | None
    entity_type: str
    entity_id: str
    actor_id: str | None
    action: str | None
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    evidence_level: str = "legacy / limited-evidence"


def legacy_history_evidence(record: Any) -> LegacyHistoryEvidence:
    """Project the fields the legacy record actually possesses, without defaults."""
    return LegacyHistoryEvidence(
        legacy_event_id=str(getattr(record, "event_uuid", getattr(record, "id", ""))),
        occurred_at_utc=getattr(record, "occurred_at", None),
        entity_type=str(getattr(record, "entity_type", "unknown")),
        entity_id=str(getattr(record, "entity_id", "")),
        actor_id=str(actor) if (actor := getattr(record, "actor_user_id", None)) is not None else None,
        action=getattr(record, "event_category", None),
        before=getattr(record, "previous_values_json", None),
        after=getattr(record, "new_values_json", None),
    )
