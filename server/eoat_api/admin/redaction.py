from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

REDACTED_VALUE = {"_audit_value": "REDACTED"}

_SECRET_TOKENS = frozenset(
    {
        "password",
        "passwd",
        "secret",
        "token",
        "cookie",
        "authorization",
        "credential",
        "private_key",
        "privatekey",
        "client_key",
        "bind_dn",
        "bind_password",
        "database_url",
    }
)


def is_sensitive_key(key: str) -> bool:
    normalized = key.casefold().replace("-", "_")
    return any(token in normalized for token in _SECRET_TOKENS)


def redact(value: Any, *, key: str | None = None) -> Any:
    """Return a persistence-safe copy without secret material.

    The structured sentinel intentionally differs from null, empty string, and
    an absent field so event consumers can render those states honestly.
    """
    if key is not None and is_sensitive_key(key):
        return REDACTED_VALUE.copy()
    if isinstance(value, Mapping):
        return {str(child_key): redact(child_value, key=str(child_key)) for child_key, child_value in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [redact(item) for item in value]
    return value
