"""Defense-in-depth sanitizing for UI, receipts, and exception boundaries."""

from __future__ import annotations

import re
from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from deployment.common import redact_text as engine_redact_text

_SENSITIVE_KEY = re.compile(
    r"(?:pass(?:word|wd)?|secret|token|api[_-]?key|credential|authorization|private[_-]?key)", re.I
)
_ASSIGNMENT = re.compile(r"(?i)\b(password|passwd|secret|token|api[_-]?key|credential)\s*[:=]\s*([^\s,;]+)")


def redact_text(value: object) -> str:
    text = engine_redact_text(str(value))
    return _ASSIGNMENT.sub(lambda match: f"{match.group(1)}=***REDACTED***", text)


def sanitize(value: Any, *, key: str | None = None) -> Any:
    """Return a JSON-safe deep copy that cannot carry values of secret-shaped fields."""

    if key and _SENSITIVE_KEY.search(key):
        return "***REDACTED***"
    if is_dataclass(value):
        value = asdict(value)
    if isinstance(value, Enum):
        return sanitize(value.value, key=key)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(item_key): sanitize(item, key=str(item_key)) for item_key, item in value.items()}
    if isinstance(value, list | tuple | set):
        return [sanitize(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    if value is None or isinstance(value, bool | int | float):
        return value
    return redact_text(value)
