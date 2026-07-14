from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class AuthenticatedIdentity:
    external_subject: str
    username: str
    display_name: str
    email: str | None
    provider: str
    group_identifiers: tuple[str, ...]
    authentication_time: datetime
    authentication_method: str
    session_identifier: str | None = None


@dataclass(frozen=True)
class ProviderHealth:
    provider: str
    configured: bool
    available: bool
    production_approved: bool
    message: str
