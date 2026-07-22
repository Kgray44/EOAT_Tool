"""Truthful server-data freshness state shared by the EOAT Atlas desktop UI.

This module deliberately separates an authoritative server modification from a
client check, a cache load, and a page refresh.  It contains no Qt code so the
state machine can be tested with a deterministic clock.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Any

POLLING_INTERVALS_SECONDS = (15, 30, 60, 300, 900, 1800)
RETRY_DELAYS_SECONDS = (15, 30, 60, 120, 300)


class PollingState(StrEnum):
    DISABLED = "disabled"
    WAITING = "waiting"
    CHECKING = "checking"
    CURRENT = "current"
    UPDATE_AVAILABLE = "update_available"
    REFRESHING = "refreshing"
    OFFLINE_CACHED = "offline_cached"
    ERROR = "error"
    PAUSED_FOR_EDIT = "paused_for_edit"
    PAUSED_FOR_OPERATION = "paused_for_operation"
    SHUTTING_DOWN = "shutting_down"


class FreshnessProtocolError(ValueError):
    """Raised when a status response cannot safely establish data freshness."""


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def parse_server_timestamp(value: Any, field_name: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise FreshnessProtocolError(f"Data status response has no {field_name}.")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise FreshnessProtocolError(f"Data status response has an invalid {field_name}.") from exc
    return _utc(parsed)


@dataclass(frozen=True)
class FreshnessSettings:
    automatic_polling_enabled: bool = True
    polling_interval_seconds: int = 60
    refresh_when_data_changes: str = "notify"
    pause_refresh_while_editing: bool = True
    poll_while_minimized: bool = True
    timestamp_display: str = "relative"
    request_timeout_seconds: int = 10

    @classmethod
    def from_mapping(cls, settings: dict[str, Any] | None) -> FreshnessSettings:
        raw = settings or {}
        try:
            interval = int(raw.get("polling_interval_seconds", 60))
        except (TypeError, ValueError):
            interval = 60
        if interval not in POLLING_INTERVALS_SECONDS:
            interval = 60
        refresh_mode = str(raw.get("refresh_when_data_changes", "notify") or "notify")
        if refresh_mode not in {"automatic", "notify"}:
            refresh_mode = "notify"
        timestamp_display = str(raw.get("timestamp_display", "relative") or "relative")
        if timestamp_display not in {"relative", "exact"}:
            timestamp_display = "relative"
        try:
            timeout = int(raw.get("request_timeout_seconds", 10))
        except (TypeError, ValueError):
            timeout = 10
        return cls(
            automatic_polling_enabled=bool(raw.get("automatic_polling_enabled", True)),
            polling_interval_seconds=interval,
            refresh_when_data_changes=refresh_mode,
            pause_refresh_while_editing=bool(raw.get("pause_refresh_while_editing", True)),
            poll_while_minimized=bool(raw.get("poll_while_minimized", True)),
            timestamp_display=timestamp_display,
            request_timeout_seconds=max(1, min(timeout, 60)),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "automatic_polling_enabled": self.automatic_polling_enabled,
            "polling_interval_seconds": self.polling_interval_seconds,
            "refresh_when_data_changes": self.refresh_when_data_changes,
            "pause_refresh_while_editing": self.pause_refresh_while_editing,
            "poll_while_minimized": self.poll_while_minimized,
            "timestamp_display": self.timestamp_display,
            "request_timeout_seconds": self.request_timeout_seconds,
        }


@dataclass
class PageFreshness:
    page_key: str
    displayed_revision: int | None = None
    last_refreshed_at: datetime | None = None
    stale: bool = False
    refresh_pending: bool = False
    refresh_deferred_reason: str = ""
    showing_cached_data: bool = False


@dataclass(frozen=True)
class FreshnessTransition:
    kind: str
    revision: int | None
    refresh_required: bool = False
    warning: str = ""


def format_exact_timestamp(value: datetime | None) -> str:
    if value is None:
        return "Unavailable"
    local = _utc(value).astimezone()
    clock = local.strftime("%I:%M:%S %p").lstrip("0")
    return f"{local.strftime('%B')} {local.day}, {local.year} at {clock}"


def format_relative_timestamp(value: datetime | None, *, now: datetime) -> str:
    """Format a server-origin timestamp without inventing freshness from `now`."""
    if value is None:
        return "unavailable"
    current = _utc(now)
    timestamp = _utc(value)
    delta = current - timestamp
    # A large negative age means the clocks are not trustworthy enough for a
    # relative claim.  The exact server timestamp remains useful.
    if delta < timedelta(seconds=-90):
        return format_exact_timestamp(timestamp)
    seconds = max(0, int(delta.total_seconds()))
    if seconds < 60:
        return "just now"
    minutes = seconds // 60
    if minutes == 1:
        return "1 minute ago"
    if minutes < 60:
        return f"{minutes} minutes ago"
    local_timestamp = timestamp.astimezone()
    local_now = current.astimezone()
    if local_timestamp.date() == local_now.date():
        return f"Today at {local_timestamp.strftime('%I:%M %p').lstrip('0')}"
    if local_timestamp.date() == (local_now.date() - timedelta(days=1)):
        return f"Yesterday at {local_timestamp.strftime('%I:%M %p').lstrip('0')}"
    year = f", {local_timestamp.year}" if local_timestamp.year != local_now.year else ""
    return f"{local_timestamp.strftime('%B')} {local_timestamp.day}{year} at {local_timestamp.strftime('%I:%M %p').lstrip('0')}"


@dataclass
class DataFreshnessService:
    """Owns freshness truth, retry policy, and displayed-page revision state.

    Callers perform I/O elsewhere, call :meth:`begin_check` before a request,
    then complete it with :meth:`receive_status` or :meth:`record_failure`.
    This makes overlapping requests impossible without tying tests to a GUI
    event loop.
    """

    settings: FreshnessSettings = field(default_factory=FreshnessSettings)
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)
    current_revision: int | None = None
    data_last_modified_at: datetime | None = None
    last_checked_at: datetime | None = None
    last_attempted_at: datetime | None = None
    server_time: datetime | None = None
    last_import_at: datetime | None = None
    last_import_source: str = ""
    data_source: str = ""
    environment: str = ""
    clock_offset_seconds: float | None = None
    state: PollingState = PollingState.WAITING
    consecutive_failures: int = 0
    retry_delay_seconds: int = 0
    last_error: str = ""
    refresh_deferred_reason: str = ""
    pages: dict[str, PageFreshness] = field(default_factory=dict)
    _check_active: bool = False
    _shutting_down: bool = False

    def configure(self, settings: FreshnessSettings) -> None:
        self.settings = settings
        if self._shutting_down:
            return
        if not settings.automatic_polling_enabled:
            self.state = PollingState.DISABLED
        elif self.state == PollingState.DISABLED:
            self.state = PollingState.WAITING

    @property
    def check_active(self) -> bool:
        return self._check_active

    @property
    def next_delay_seconds(self) -> int:
        return self.retry_delay_seconds or self.settings.polling_interval_seconds

    def begin_check(self, *, manual: bool = False) -> bool:
        if self._shutting_down or self._check_active or (not manual and not self.settings.automatic_polling_enabled):
            return False
        self._check_active = True
        self.last_attempted_at = _utc(self.now())
        self.state = PollingState.CHECKING
        return True

    def receive_status(self, payload: dict[str, Any], *, received_at: datetime | None = None) -> FreshnessTransition:
        if not isinstance(payload, dict):
            raise FreshnessProtocolError("Data status response is not an object.")
        if payload.get("status") != "available":
            raise FreshnessProtocolError("Data status response did not report available data.")
        revision = payload.get("data_revision")
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
            raise FreshnessProtocolError("Data status response has an invalid data_revision.")
        modified_at = parse_server_timestamp(payload.get("data_last_modified_at"), "data_last_modified_at")
        server_time = parse_server_timestamp(payload.get("server_time"), "server_time")
        received = _utc(received_at or self.now())
        previous = self.current_revision
        self._check_active = False
        self.last_checked_at = received
        self.server_time = server_time
        self.clock_offset_seconds = (server_time - received).total_seconds()
        self.last_import_at = (
            parse_server_timestamp(payload["last_import_at"], "last_import_at")
            if payload.get("last_import_at")
            else None
        )
        self.last_import_source = str(payload.get("last_import_source") or "")
        self.data_source = str(payload.get("source") or "")
        self.environment = str(payload.get("environment") or "")
        self.consecutive_failures = 0
        self.retry_delay_seconds = 0
        self.last_error = ""
        settled_state = PollingState.DISABLED if not self.settings.automatic_polling_enabled else PollingState.CURRENT

        if previous is None:
            self.current_revision = revision
            self.data_last_modified_at = modified_at
            self._mark_pages_stale(revision)
            self.state = settled_state
            return FreshnessTransition("initial", revision, refresh_required=False)
        if revision == previous:
            # A no-change check advances only Last checked.  Preserve the
            # earlier modification timestamp even if a bad server sends a
            # different timestamp alongside the same revision.  A snapshot
            # can establish its revision before the first status-only poll;
            # in that bootstrap case there is no client timestamp to
            # preserve, so adopt the first authoritative value.
            if self.data_last_modified_at is None:
                self.data_last_modified_at = modified_at
            self.state = settled_state if not self.any_page_stale else PollingState.UPDATE_AVAILABLE
            return FreshnessTransition("unchanged", revision)
        if revision > previous:
            self.current_revision = revision
            self.data_last_modified_at = modified_at
            self._mark_pages_stale(revision)
            self.state = PollingState.UPDATE_AVAILABLE
            return FreshnessTransition("advanced", revision, refresh_required=True)

        # A lower revision is meaningful: a restore, environment switch, or
        # rollback.  Invalidate all optimistic displayed-revision assumptions.
        self.current_revision = revision
        self.data_last_modified_at = modified_at
        self._mark_pages_stale(revision, force_all=True)
        self.state = PollingState.UPDATE_AVAILABLE
        return FreshnessTransition(
            "decreased",
            revision,
            refresh_required=True,
            warning="Server data revision decreased; EOAT Atlas will safely reload before treating data as current.",
        )

    def record_failure(self, error: BaseException | str) -> None:
        self._check_active = False
        self.consecutive_failures += 1
        self.retry_delay_seconds = RETRY_DELAYS_SECONDS[
            min(self.consecutive_failures - 1, len(RETRY_DELAYS_SECONDS) - 1)
        ]
        self.last_error = str(error)
        self.state = PollingState.OFFLINE_CACHED if self.current_revision is not None else PollingState.ERROR

    def mark_refreshing(self) -> None:
        if not self._shutting_down:
            self.state = PollingState.REFRESHING

    def mark_refresh_deferred(self, reason: str) -> None:
        self.refresh_deferred_reason = reason
        for page in self.pages.values():
            if page.stale:
                page.refresh_pending = True
                page.refresh_deferred_reason = reason
        self.state = PollingState.PAUSED_FOR_EDIT if reason == "editing" else PollingState.PAUSED_FOR_OPERATION

    def clear_refresh_deferred(self) -> None:
        self.refresh_deferred_reason = ""
        for page in self.pages.values():
            page.refresh_deferred_reason = ""

    def register_page(
        self, page_key: str, *, displayed_revision: int | None = None, cached: bool = False
    ) -> PageFreshness:
        page = self.pages.setdefault(page_key, PageFreshness(page_key=page_key))
        if displayed_revision is not None:
            page.displayed_revision = displayed_revision
        page.showing_cached_data = cached
        page.stale = self.current_revision is not None and page.displayed_revision != self.current_revision
        return page

    def mark_page_applied(self, page_key: str, revision: int | None = None, *, cached: bool = False) -> None:
        page = self.register_page(page_key)
        page.displayed_revision = self.current_revision if revision is None else revision
        page.last_refreshed_at = _utc(self.now())
        page.showing_cached_data = cached
        page.stale = self.current_revision is not None and page.displayed_revision != self.current_revision
        page.refresh_pending = page.stale
        if not page.stale:
            page.refresh_deferred_reason = ""
        if not self.any_page_stale and self.state in {
            PollingState.UPDATE_AVAILABLE,
            PollingState.REFRESHING,
            PollingState.PAUSED_FOR_EDIT,
            PollingState.PAUSED_FOR_OPERATION,
        }:
            self.state = PollingState.CURRENT

    @property
    def any_page_stale(self) -> bool:
        return any(page.stale for page in self.pages.values())

    def _mark_pages_stale(self, revision: int, *, force_all: bool = False) -> None:
        for page in self.pages.values():
            page.stale = force_all or page.displayed_revision != revision
            page.refresh_pending = page.stale

    def finish_refresh(self, *, revision: int | None = None) -> None:
        target = self.current_revision if revision is None else revision
        for page in self.pages.values():
            page.displayed_revision = target
            page.last_refreshed_at = _utc(self.now())
            page.stale = False
            page.refresh_pending = False
            page.refresh_deferred_reason = ""
        self.refresh_deferred_reason = ""
        self.state = PollingState.CURRENT

    def shutdown(self) -> None:
        self._shutting_down = True
        self._check_active = False
        self.state = PollingState.SHUTTING_DOWN

    def relative_now(self) -> datetime:
        now = _utc(self.now())
        if self.clock_offset_seconds is None:
            return now
        return now + timedelta(seconds=self.clock_offset_seconds)

    def primary_text(self) -> str:
        if self.state == PollingState.CHECKING:
            return "Checking for updates…"
        if self.state == PollingState.REFRESHING:
            return "Refreshing data…"
        if self.state == PollingState.DISABLED:
            return "Manual updates enabled"
        if self.state == PollingState.PAUSED_FOR_EDIT:
            return "Update available · Refresh paused while editing"
        if self.state == PollingState.PAUSED_FOR_OPERATION:
            return "Update available · Refresh paused while an operation is in progress"
        if self.state == PollingState.OFFLINE_CACHED:
            verified = format_relative_timestamp(self.last_checked_at, now=self.relative_now())
            return f"Offline · Showing cached data · Last verified {verified}"
        if self.state == PollingState.ERROR:
            return "Could not check for updates"
        if self.data_last_modified_at is None:
            return "Data freshness unknown"
        if self.settings.timestamp_display == "exact":
            detail = format_exact_timestamp(self.data_last_modified_at)
        else:
            detail = format_relative_timestamp(self.data_last_modified_at, now=self.relative_now())
        prefix = "New data available" if self.state == PollingState.UPDATE_AVAILABLE else "Data last updated"
        return f"{prefix} {detail}"

    def details_text(self, *, page_key: str = "") -> str:
        page = self.pages.get(page_key)
        rows = [
            f"Data last updated: {format_exact_timestamp(self.data_last_modified_at)}",
            f"Last checked: {format_exact_timestamp(self.last_checked_at)}",
            f"Server revision: {self.current_revision if self.current_revision is not None else 'Unavailable'}",
        ]
        if page is not None:
            rows.extend(
                (
                    f"Current page revision: {page.displayed_revision if page.displayed_revision is not None else 'Unavailable'}",
                    f"This page refreshed: {format_exact_timestamp(page.last_refreshed_at)}",
                )
            )
        if self.last_import_at is not None:
            rows.append(f"Last import: {format_exact_timestamp(self.last_import_at)}")
        if self.last_import_source:
            rows.append(f"Last import source: {self.last_import_source}")
        rows.extend(
            (
                f"Data source: {self.data_source or 'Unavailable'}",
                f"Environment: {self.environment or 'Unavailable'}",
                f"Automatic polling: {'Every ' + _interval_label(self.settings.polling_interval_seconds) if self.settings.automatic_polling_enabled else 'Disabled'}",
                f"Connection: {self.state.replace('_', ' ').title()}",
            )
        )
        if self.refresh_deferred_reason:
            rows.append(f"Refresh deferred: {self.refresh_deferred_reason}")
        return "\n".join(rows)

    def diagnostics(self, *, page_key: str = "") -> dict[str, Any]:
        page = self.pages.get(page_key)
        return {
            "polling_enabled": self.settings.automatic_polling_enabled,
            "configured_interval_seconds": self.settings.polling_interval_seconds,
            "effective_interval_seconds": self.next_delay_seconds,
            "polling_state": self.state,
            "last_poll_attempted": self.last_attempted_at.isoformat() if self.last_attempted_at else "",
            "last_poll_succeeded": self.last_checked_at.isoformat() if self.last_checked_at else "",
            "consecutive_failures": self.consecutive_failures,
            "current_retry_delay_seconds": self.retry_delay_seconds,
            "last_error": self.last_error,
            "current_server_revision": self.current_revision,
            "current_page_revision": page.displayed_revision if page else None,
            "data_last_modified_at": self.data_last_modified_at.isoformat() if self.data_last_modified_at else "",
            "last_import_at": self.last_import_at.isoformat() if self.last_import_at else "",
            "last_import_source": self.last_import_source,
            "clock_offset_seconds": self.clock_offset_seconds,
            "data_source": self.data_source,
            "environment": self.environment,
            "cache_status": "cached"
            if any(item.showing_cached_data for item in self.pages.values())
            else "server-backed",
            "refresh_deferred": bool(self.refresh_deferred_reason),
            "refresh_deferred_reason": self.refresh_deferred_reason,
            "active_polling_tasks": int(self._check_active),
        }


def _interval_label(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds} seconds"
    minutes = seconds // 60
    return f"{minutes} minute" if minutes == 1 else f"{minutes} minutes"


__all__ = [
    "DataFreshnessService",
    "FreshnessProtocolError",
    "FreshnessSettings",
    "FreshnessTransition",
    "POLLING_INTERVALS_SECONDS",
    "PageFreshness",
    "PollingState",
    "format_exact_timestamp",
    "format_relative_timestamp",
    "parse_server_timestamp",
]
