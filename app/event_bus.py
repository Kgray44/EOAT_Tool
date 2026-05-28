from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable


EVENT_AUDIT_SAVED = "AuditSaved"
EVENT_AUDIT_LOADED = "AuditLoaded"
EVENT_ANNOTATION_CHANGED = "AnnotationChanged"
EVENT_TAG_CHANGED = "TagChanged"
EVENT_TAG_COLOR_SYNCED = "TagColorSynced"
EVENT_ROBOT_INFO_UPDATED = "RobotInfoUpdated"
EVENT_COMPATIBILITY_REGENERATED = "CompatibilityRegenerated"
EVENT_WORKBOOK_VALIDATED = "WorkbookValidated"
EVENT_REPORT_GENERATED = "ReportGenerated"
EVENT_DASHBOARD_CACHE_INVALIDATED = "DashboardCacheInvalidated"
EVENT_PROJECT_ROOT_CHANGED = "ProjectRootChanged"
EVENT_SETTINGS_CHANGED = "SettingsChanged"
EVENT_SCHEDULED_REPORT_RAN = "ScheduledReportRan"
EVENT_OPEN_ITEMS_CHANGED = "OpenItemsChanged"
EVENT_ANY = "*"


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class AppEvent:
    event_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    source: str = ""
    timestamp: str = field(default_factory=_utc_timestamp)


EventHandler = Callable[[AppEvent], None]


class EventBus:
    def __init__(self):
        self._subscribers: dict[str, list[EventHandler]] = {}

    def subscribe(self, event_type: str, handler: EventHandler) -> Callable[[], None]:
        key = event_type or EVENT_ANY
        self._subscribers.setdefault(key, []).append(handler)

        def _unsubscribe() -> None:
            self.unsubscribe(key, handler)

        return _unsubscribe

    def unsubscribe(self, event_type: str, handler: EventHandler) -> None:
        key = event_type or EVENT_ANY
        handlers = self._subscribers.get(key)
        if not handlers:
            return
        self._subscribers[key] = [candidate for candidate in handlers if candidate != handler]
        if not self._subscribers[key]:
            self._subscribers.pop(key, None)

    def emit(self, event_type: str, payload: dict[str, Any] | None = None, *, source: str = "") -> AppEvent:
        event = AppEvent(event_type=event_type, payload=dict(payload or {}), source=source)
        self.publish(event)
        return event

    def publish(self, event: AppEvent) -> None:
        handlers: list[EventHandler] = []
        for candidate in [
            *self._subscribers.get(event.event_type, []),
            *self._subscribers.get(EVENT_ANY, []),
        ]:
            if not any(existing == candidate for existing in handlers):
                handlers.append(candidate)
        for handler in handlers:
            handler(event)

    def clear(self) -> None:
        self._subscribers.clear()


_event_bus = EventBus()


def get_event_bus() -> EventBus:
    return _event_bus
