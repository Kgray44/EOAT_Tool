from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

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
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EventHandlerError:
    event_type: str
    handler: str
    error: str
    timestamp: str = field(default_factory=_utc_timestamp)


class EventBus:
    def __init__(self):
        self._subscribers: dict[str, list[EventHandler]] = {}
        self._handler_errors: list[EventHandlerError] = []

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
            try:
                handler(event)
            except Exception as exc:
                error = EventHandlerError(event.event_type, _handler_name(handler), str(exc))
                self._handler_errors.append(error)
                logger.exception("Event handler failed for %s in %s", event.event_type, error.handler)

    def clear(self) -> None:
        self._subscribers.clear()
        self._handler_errors.clear()

    def subscriber_count(self, event_type: str | None = None) -> int:
        if event_type is not None:
            return len(self._subscribers.get(event_type or EVENT_ANY, ()))
        return sum(len(handlers) for handlers in self._subscribers.values())

    def subscribed_event_types(self) -> tuple[str, ...]:
        return tuple(sorted(self._subscribers))

    def handler_errors(self) -> tuple[EventHandlerError, ...]:
        return tuple(self._handler_errors)


def _handler_name(handler: EventHandler) -> str:
    name = getattr(handler, "__qualname__", None) or getattr(handler, "__name__", None)
    if name:
        return str(name)
    owner = getattr(handler, "__self__", None)
    if owner is not None:
        return f"{owner.__class__.__name__}.{handler.__class__.__name__}"
    return repr(handler)


_event_bus = EventBus()


def get_event_bus() -> EventBus:
    return _event_bus
