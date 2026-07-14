from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class ConnectivityMode(StrEnum):
    ONLINE = "ONLINE"
    OFFLINE_READ_ONLY = "OFFLINE_READ_ONLY"
    INCOMPATIBLE_SERVER = "INCOMPATIBLE_SERVER"
    INITIALIZING = "INITIALIZING"
    REFRESHING = "REFRESHING"
    ERROR = "ERROR"


@dataclass(frozen=True)
class ConnectionStatus:
    mode: ConnectivityMode
    message: str
    api_version: str = ""
    schema_revision: str = ""
    last_checked_at: str = ""


@dataclass(frozen=True)
class CacheStatus:
    path: str
    exists: bool
    schema_version: str
    api_version: str
    server_schema_revision: str
    last_successful_sync_at: str
    last_full_refresh_at: str
    last_change_cursor: int
    server_revision: str
    entity_counts: dict[str, int]


JsonObject = dict[str, Any]
