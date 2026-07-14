from __future__ import annotations

import hashlib
import os
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol

from core.audit.history import read_audit_history

EVENT_CATEGORIES = (
    "LOCATION",
    "AUDIT",
    "MAINTENANCE",
    "STATUS",
    "TOOL",
    "DOCUMENTATION",
    "INSPECTION",
    "IMPORT",
    "ISSUE",
    "OTHER",
)


@dataclass(frozen=True)
class EOATHistorySourceRecord:
    source_type: str
    source_record_id: str
    payload: Mapping[str, Any]


@dataclass(frozen=True)
class EOATHistoryEvent:
    event_id: str
    eoat_id: str
    event_type: str
    title: str
    event_category: str = "OTHER"
    description: str = ""
    event_timestamp: datetime | None = None
    effective_from: datetime | None = None
    effective_until: datetime | None = None
    machine_id: str = ""
    machine_display_name: str = ""
    previous_machine_id: str = ""
    previous_machine_display_name: str = ""
    tool_number: str = ""
    previous_tool_number: str = ""
    robot_number: str = ""
    storage_location: str = ""
    document_reference: str = ""
    photo_reference: str = ""
    previous_status: str = ""
    new_status: str = ""
    reason: str = ""
    notes: str = ""
    audit_id: str = ""
    maintenance_id: str = ""
    recorded_by: str = ""
    app_instance_id: str = ""
    source_type: str = ""
    source_record_id: str = ""
    transaction_id: str = ""
    is_verified: bool | None = None
    is_approximate_date: bool = False
    previous_values: Mapping[str, Any] = field(default_factory=dict)
    new_values: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def effective_timestamp(self) -> datetime | None:
        return self.effective_from or self.event_timestamp

    @property
    def machine_label(self) -> str:
        return self.machine_display_name or self.machine_id

    @property
    def previous_machine_label(self) -> str:
        return self.previous_machine_display_name or self.previous_machine_id


@dataclass(frozen=True)
class EOATHistoryViewModel:
    eoat_id: str
    events: tuple[EOATHistoryEvent, ...]
    event_types: tuple[str, ...]
    machines: tuple[str, ...]
    delivery_mode: str = "online"
    cache_timestamp: str = ""


@dataclass(frozen=True)
class EOATHistoryExportModel:
    eoat_id: str
    events: tuple[EOATHistoryEvent, ...]
    total_events: int
    first_event_at: datetime | None
    last_event_at: datetime | None
    event_type_counts: tuple[tuple[str, int], ...]
    machines: tuple[str, ...]
    delivery_mode: str = "online"
    cache_timestamp: str = ""


class EOATHistoryRepository(Protocol):
    def get_history(self, eoat_id: str) -> Iterable[EOATHistorySourceRecord]: ...


class LegacyAuditHistoryRepository:
    """Read genuine legacy audit-save events from the existing project JSONL log."""

    _EOAT_KEYS = ("EOAT Assembly ID", "EOAT ID", "Assembly ID", "eoat_id")

    def __init__(self, project_root: str | Path):
        self.project_root = Path(project_root)

    def get_history(self, eoat_id: str) -> tuple[EOATHistorySourceRecord, ...]:
        target = _identity(eoat_id)
        matches: list[EOATHistorySourceRecord] = []
        for index, row in enumerate(read_audit_history(self.project_root)):
            before = _mapping(row.get("previous_row_data"))
            after = _mapping(row.get("new_row_data"))
            values = [_text(after.get(key) or before.get(key)) for key in self._EOAT_KEYS]
            if target not in {_identity(value) for value in values if value}:
                continue
            source_id = _text(row.get("source_record_id") or row.get("audit_id"))
            if not source_id:
                source_id = f"line-{index + 1}"
            matches.append(EOATHistorySourceRecord("legacy_audit_jsonl", source_id, row))
        return tuple(matches)


class GatewayEOATHistoryRepository:
    """Use the configured API gateway; this is never selected in legacy mode."""

    def get_history(self, eoat_id: str) -> tuple[EOATHistorySourceRecord, ...]:
        from core.data_gateway import AtlasDataGateway

        gateway = AtlasDataGateway()
        try:
            rows = gateway.get_eoat_history(eoat_id)
        finally:
            gateway.close()
        output = []
        for index, row in enumerate(rows or ()):
            payload = _mapping(row)
            source_id = _text(payload.get("source_record_id") or payload.get("event_id")) or f"api-{index + 1}"
            output.append(EOATHistorySourceRecord("mysql_api", source_id, payload))
        return tuple(output)


def configured_eoat_history_repository(project_root: str | Path) -> EOATHistoryRepository:
    backend = os.getenv("EOAT_ATLAS_DATA_BACKEND", "legacy").strip().casefold()
    if backend == "mysql_api":
        return GatewayEOATHistoryRepository()
    return LegacyAuditHistoryRepository(project_root)


class EOATHistoryService:
    def __init__(self, repository: EOATHistoryRepository):
        self.repository = repository

    def history_for(self, eoat_id: str) -> EOATHistoryViewModel:
        normalized: list[EOATHistoryEvent] = []
        seen: set[str] = set()
        for source in self.repository.get_history(eoat_id):
            event = self._normalize(eoat_id, source)
            if event.event_id in seen:
                continue
            seen.add(event.event_id)
            normalized.append(event)
        events = tuple(sorted(normalized, key=_event_sort_key))
        event_types = tuple(sorted({event.event_type for event in events}))
        machines = tuple(sorted({value for event in events for value in _event_machines(event)}, key=str.casefold))
        modes = {_text(event.metadata.get("delivery_mode")) for event in events if event.metadata.get("delivery_mode")}
        delivery_mode = "offline_cache" if "offline_cache" in modes else "online"
        cache_timestamp = next((_text(event.metadata.get("cache_timestamp")) for event in events if event.metadata.get("cache_timestamp")), "")
        return EOATHistoryViewModel(
            eoat_id=_text(eoat_id),
            events=events,
            event_types=event_types,
            machines=machines,
            delivery_mode=delivery_mode,
            cache_timestamp=cache_timestamp,
        )

    def filter_events(
        self,
        events: Iterable[EOATHistoryEvent],
        *,
        search: str = "",
        event_type: str = "All",
        machine: str = "All",
        date_range: str = "All",
        now: datetime | None = None,
    ) -> tuple[EOATHistoryEvent, ...]:
        query = search.strip().casefold()
        kind = event_type.strip().upper()
        machine_key = machine.strip().casefold()
        reference = now or datetime.now(timezone.utc)
        output = []
        for event in events:
            if kind not in {"", "ALL"} and event.event_type != kind and event.event_category != kind:
                continue
            if machine_key not in {"", "all"} and machine_key not in {item.casefold() for item in _event_machines(event)}:
                continue
            if not _in_date_range(event.effective_timestamp, date_range, reference):
                continue
            if query and query not in _event_search_text(event):
                continue
            output.append(event)
        return tuple(sorted(output, key=_event_sort_key))

    def export_model(self, eoat_id: str, events: Iterable[EOATHistoryEvent]) -> EOATHistoryExportModel:
        ordered = tuple(sorted(events, key=_event_sort_key))
        dated = [event.effective_timestamp for event in ordered if event.effective_timestamp is not None]
        counts = Counter(event.event_type for event in ordered)
        return EOATHistoryExportModel(
            eoat_id=_text(eoat_id),
            events=ordered,
            total_events=len(ordered),
            first_event_at=min(dated) if dated else None,
            last_event_at=max(dated) if dated else None,
            event_type_counts=tuple(sorted(counts.items())),
            machines=tuple(sorted({item for event in ordered for item in _event_machines(event)}, key=str.casefold)),
            delivery_mode="offline_cache" if any(event.metadata.get("delivery_mode") == "offline_cache" for event in ordered) else "online",
            cache_timestamp=next((_text(event.metadata.get("cache_timestamp")) for event in ordered if event.metadata.get("cache_timestamp")), ""),
        )

    def _normalize(self, eoat_id: str, source: EOATHistorySourceRecord) -> EOATHistoryEvent:
        payload = source.payload
        if source.source_type == "legacy_audit_jsonl":
            return _legacy_audit_event(eoat_id, source)
        details = _mapping(payload.get("details"))
        merged = {**details, **payload}
        raw_type = _text(merged.get("event_type") or merged.get("type"))
        explicit_category = _text(merged.get("event_category"))
        category = explicit_category or normalize_event_type(raw_type)
        timestamp, approximate = _parse_timestamp(merged.get("effective_from") or merged.get("occurred_at") or merged.get("event_timestamp"))
        logged_at, logged_approximate = _parse_timestamp(merged.get("logged_at") or merged.get("created_at"))
        event_id = _text(merged.get("event_id")) or _stable_event_id(source.source_type, source.source_record_id, eoat_id, raw_type, timestamp or logged_at)
        title = _text(merged.get("title") or merged.get("summary")) or display_title(category, merged)
        return EOATHistoryEvent(
            event_id=event_id,
            eoat_id=_text(eoat_id),
            event_type=(raw_type.upper() if explicit_category else category.upper()) or "OTHER",
            title=title,
            event_category=category.upper(),
            description=_text(merged.get("description")),
            event_timestamp=logged_at or timestamp,
            effective_from=timestamp,
            effective_until=_parse_timestamp(merged.get("effective_until"))[0],
            machine_id=_text(merged.get("related_machine") or merged.get("machine_id") or merged.get("machine")),
            machine_display_name=_text(merged.get("machine_display_name")),
            previous_machine_id=_text(merged.get("previous_machine_id") or merged.get("previous_machine")),
            previous_machine_display_name=_text(merged.get("previous_machine_display_name")),
            tool_number=_text(merged.get("related_tool") or merged.get("tool_number") or merged.get("tool")),
            previous_tool_number=_text(merged.get("previous_tool_number")),
            robot_number=_text(merged.get("related_robot") or merged.get("robot_number")),
            storage_location=_text(merged.get("related_storage_location") or merged.get("storage_location")),
            document_reference=_text(merged.get("related_document") or merged.get("document_uuid")),
            photo_reference=_text(merged.get("related_photo") or merged.get("photo_id")),
            previous_status=_text(merged.get("previous_status")),
            new_status=_text(merged.get("new_status") or merged.get("status")),
            reason=_text(merged.get("reason")),
            notes=_text(merged.get("notes")),
            audit_id=_text(merged.get("audit_id")),
            maintenance_id=_text(merged.get("maintenance_id")),
            recorded_by=_text(merged.get("actor") or merged.get("recorded_by") or merged.get("logged_by")),
            app_instance_id=_text(merged.get("application_instance") or merged.get("app_instance_id")),
            source_type=_text(merged.get("source_record_type") or merged.get("source") or source.source_type),
            source_record_id=source.source_record_id,
            transaction_id=_text(merged.get("transaction_id")),
            is_verified=_optional_bool(merged.get("is_verified")),
            is_approximate_date=approximate or logged_approximate,
            previous_values=_mapping(merged.get("previous_values")),
            new_values=_mapping(merged.get("new_values")),
            metadata={**details, **_mapping(merged.get("metadata"))},
        )


def normalize_event_type(value: Any) -> str:
    text = _text(value).casefold()
    if any(word in text for word in ("install", "remove", "transfer", "location", "storage", "machine assignment", "off-machine")):
        return "LOCATION"
    if "audit" in text:
        return "AUDIT"
    if any(word in text for word in ("maintenance", "preventive", "corrective", "repair", "pm")):
        return "MAINTENANCE"
    if "status" in text or "condition" in text:
        return "STATUS"
    if "tool" in text or "mold" in text:
        return "TOOL"
    if any(word in text for word in ("document", "record change", "update")):
        return "DOCUMENTATION"
    if "inspect" in text:
        return "INSPECTION"
    if any(word in text for word in ("import", "legacy", "migration")):
        return "IMPORT"
    if any(word in text for word in ("issue", "failure", "damage")):
        return "ISSUE"
    return "OTHER"


def display_title(category: str, values: Mapping[str, Any]) -> str:
    machine = _text(values.get("machine_display_name") or values.get("machine") or values.get("machine_id"))
    titles = {
        "AUDIT": "Physical Audit Completed",
        "MAINTENANCE": "Maintenance Completed",
        "STATUS": "Status Changed",
        "TOOL": "Tool Association Updated",
        "DOCUMENTATION": "Record Updated",
        "INSPECTION": "Inspection Completed",
        "IMPORT": "Imported Legacy Record",
        "ISSUE": "Issue Documented",
        "OTHER": "History Event",
    }
    if category == "LOCATION":
        return f"Machine Assignment Updated{f' — {machine}' if machine else ''}"
    return titles.get(category, "History Event")


def _legacy_audit_event(eoat_id: str, source: EOATHistorySourceRecord) -> EOATHistoryEvent:
    row = source.payload
    before = _mapping(row.get("previous_row_data"))
    after = _mapping(row.get("new_row_data"))
    timestamp, approximate = _parse_timestamp(row.get("timestamp"))
    audit_date, audit_approximate = _parse_timestamp(after.get("Audit Date") or before.get("Audit Date"))
    raw_type = _text(row.get("event_type"))
    created = any(word in raw_type.casefold() for word in ("create", "new", "complete"))
    title = "Physical Audit Completed" if created else "Audit Record Updated"
    machine = _first(after, before, ("Press/Machine #", "Machine #", "Machine"))
    tool = _first(after, before, ("Tool #", "Tool Number", "Mold/Tool #"))
    notes = _first(after, before, ("Notes", "Known Issues", "Drop/Mis-Pick History"))
    reason = ", ".join(str(item) for item in row.get("changed_fields", ()) if str(item).strip())
    event_id = _stable_event_id(source.source_type, source.source_record_id, eoat_id, raw_type, timestamp or audit_date)
    return EOATHistoryEvent(
        event_id=event_id,
        eoat_id=_text(eoat_id),
        event_type="AUDIT",
        title=title,
        event_category="AUDITS",
        event_timestamp=timestamp,
        effective_from=audit_date or timestamp,
        machine_id=machine,
        tool_number=tool,
        new_status=_first(after, before, ("Status", "Condition")),
        reason=f"Updated fields: {reason}" if reason else "",
        notes=notes,
        audit_id=_text(row.get("audit_id") or after.get("Audit ID") or before.get("Audit ID")),
        recorded_by=_text(row.get("auditor") or after.get("Auditor") or before.get("Auditor")),
        source_type=_text(row.get("source")) or source.source_type,
        source_record_id=source.source_record_id,
        is_verified=True,
        is_approximate_date=approximate or audit_approximate,
        metadata={"changed_fields": tuple(row.get("changed_fields", ()) or ())},
    )


def _event_sort_key(event: EOATHistoryEvent) -> tuple[float, str]:
    timestamp = event.effective_timestamp or datetime.min.replace(tzinfo=timezone.utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return (-timestamp.timestamp(), event.event_id)


def _event_machines(event: EOATHistoryEvent) -> tuple[str, ...]:
    values = []
    for value in (event.machine_label, event.previous_machine_label):
        value = _text(value)
        if value and value not in values:
            values.append(value)
    if not values and (event.new_status.casefold() == "off-machine" or "off-machine" in event.title.casefold()):
        values.append("Off-Machine")
    return tuple(values)


def _event_search_text(event: EOATHistoryEvent) -> str:
    values = (
        event.title,
        event.event_type,
        event.machine_label,
        event.previous_machine_label,
        event.tool_number,
        event.previous_tool_number,
        event.reason,
        event.notes,
        event.audit_id,
        event.maintenance_id,
        event.recorded_by,
        event.source_type,
    )
    return " ".join(values).casefold()


def _in_date_range(timestamp: datetime | None, date_range: str, now: datetime) -> bool:
    choice = date_range.strip().casefold()
    if choice in {"", "all"}:
        return True
    if timestamp is None:
        return False
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    if choice == "last 30 days":
        return timestamp >= now - timedelta(days=30)
    if choice == "last 90 days":
        return timestamp >= now - timedelta(days=90)
    if choice == "this year":
        return timestamp.year == now.year
    if choice == "previous year":
        return timestamp.year == now.year - 1
    return True


def _parse_timestamp(value: Any) -> tuple[datetime | None, bool]:
    if isinstance(value, datetime):
        parsed = value
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed, False
    text = _text(value)
    if not text:
        return None, False
    approximate = any(token in text.casefold() for token in ("approx", "circa", "~"))
    cleaned = text.replace("~", "").replace("circa", "").replace("Circa", "").strip()
    try:
        parsed = datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
    except ValueError:
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%b %d, %Y", "%Y"):
            try:
                parsed = datetime.strptime(cleaned, fmt)
                approximate = approximate or fmt == "%Y"
                break
            except ValueError:
                continue
        else:
            return None, approximate
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed, approximate


def _stable_event_id(source: str, source_id: str, eoat_id: str, event_type: str, timestamp: datetime | None) -> str:
    raw = "|".join((_text(source), _text(source_id), _identity(eoat_id), _text(event_type), timestamp.isoformat() if timestamp else ""))
    return hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:20]


def _first(primary: Mapping[str, Any], secondary: Mapping[str, Any], keys: Iterable[str]) -> str:
    for key in keys:
        value = _text(primary.get(key) or secondary.get(key))
        if value:
            return value
    return ""


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _identity(value: Any) -> str:
    return "".join(character for character in _text(value).casefold() if character.isalnum())


def _optional_bool(value: Any) -> bool | None:
    if value is None or _text(value) == "":
        return None
    if isinstance(value, bool):
        return value
    return _text(value).casefold() in {"1", "true", "yes", "verified"}


__all__ = [
    "EVENT_CATEGORIES",
    "EOATHistoryEvent",
    "EOATHistoryExportModel",
    "EOATHistoryRepository",
    "EOATHistoryService",
    "EOATHistorySourceRecord",
    "EOATHistoryViewModel",
    "GatewayEOATHistoryRepository",
    "LegacyAuditHistoryRepository",
    "configured_eoat_history_repository",
    "display_title",
    "normalize_event_type",
]
