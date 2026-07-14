from __future__ import annotations

import random
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from core.eoat_history import EOATHistoryEvent, EOATHistoryViewModel


def history_event(index: int = 0, *, eoat_id: str = "TEST-EOAT-0001", event_type: str = "AUDIT", **changes) -> EOATHistoryEvent:
    timestamp = datetime(2026, 7, 12, 14, 14, tzinfo=timezone.utc) - timedelta(days=index * 7)
    base = EOATHistoryEvent(
        event_id=f"event-{index:04d}",
        eoat_id=eoat_id,
        event_type=event_type,
        title={
            "LOCATION": "Installed on Test Machine",
            "AUDIT": "Physical Audit Completed",
            "MAINTENANCE": "Preventive Maintenance Completed",
            "STATUS": "Status Changed",
        }.get(event_type, "Documented History Event"),
        event_timestamp=timestamp,
        effective_from=timestamp,
        machine_id=f"Machine {71 + index % 3}" if event_type != "STATUS" else "",
        previous_machine_id="Off-Machine" if event_type == "LOCATION" else "",
        tool_number=f"TEST-TOOL-{index % 5:02d}",
        previous_status="In Storage" if event_type == "STATUS" else "",
        new_status="Active" if event_type == "STATUS" else "",
        reason="Fixture-only documented reason",
        notes="Fixture-only notes. These records are never loaded by production providers.",
        audit_id=f"TEST-AUD-{index:04d}" if event_type == "AUDIT" else "",
        maintenance_id=f"TEST-PM-{index:04d}" if event_type == "MAINTENANCE" else "",
        recorded_by="Test User",
        source_type="test_fixture",
        source_record_id=f"fixture-{index:04d}",
        is_verified=True,
    )
    return replace(base, **changes)


def mixed_history(count: int = 4, *, order: str = "newest") -> EOATHistoryViewModel:
    kinds = ("LOCATION", "AUDIT", "MAINTENANCE", "STATUS")
    events = [history_event(index, event_type=kinds[index % len(kinds)]) for index in range(count)]
    if order == "oldest":
        events.reverse()
    elif order == "random":
        random.Random(42).shuffle(events)
    return EOATHistoryViewModel(
        eoat_id="TEST-EOAT-0001",
        events=tuple(events),
        event_types=tuple(sorted({event.event_type for event in events})),
        machines=tuple(sorted({event.machine_label for event in events if event.machine_label})),
    )


def edge_case_history() -> EOATHistoryViewModel:
    events = list(mixed_history(25, order="random").events)
    shared = datetime(2025, 1, 1, tzinfo=timezone.utc)
    events.extend(
        [
            history_event(30, event_type="IMPORT", title="Imported Legacy Record", effective_from=shared, is_approximate_date=True),
            history_event(31, event_type="OTHER", title="Unknown event type " * 18, effective_from=shared, machine_id="", tool_number="", recorded_by="", notes=""),
            history_event(32, event_type="LOCATION", title="Removed from machine", machine_id="Off-Machine"),
            history_event(33, event_type="ISSUE", reason="Very long reason " * 80, notes="First paragraph.\n\nSecond paragraph. " * 40),
            history_event(34, event_type="AUDIT", event_timestamp=None, effective_from=None, machine_id="", tool_number=""),
        ]
    )
    return EOATHistoryViewModel(
        eoat_id="TEST-EOAT-0001",
        events=tuple(events),
        event_types=tuple(sorted({event.event_type for event in events})),
        machines=tuple(sorted({event.machine_label for event in events if event.machine_label})),
    )


__all__ = ["edge_case_history", "history_event", "mixed_history"]
