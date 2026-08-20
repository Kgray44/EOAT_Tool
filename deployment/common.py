from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


class DeploymentError(RuntimeError):
    """A safety or validation boundary prevented an operation."""


class CheckStatus(str, Enum):
    PASS = "PASS"
    WARNING = "WARNING"
    FAIL = "FAIL"
    SKIPPED = "SKIPPED"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: CheckStatus
    detail: str
    started_at_utc: str | None = None
    ended_at_utc: str | None = None
    exit_code: int | None = None


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def utc_text(value: datetime | None = None) -> str:
    return (value or utc_now()).astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_json(payload: Any) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def to_jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {key: to_jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return utc_text(value)
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [to_jsonable(item) for item in value]
    return value


def write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(to_jsonable(payload), indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="\n", dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(rendered)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


_SECRET_VALUE = re.compile(
    r"(?i)(?:password|passwd|secret|token|api[_-]?key|private[_-]?key)\s*[:=]\s*[\"']([^\"'\r\n]{8,})[\"']"
)
_CONNECTION_SECRET = re.compile(r"(?i)(?:mysql|postgres(?:ql)?|mssql)://[^\s:@/]+:[^\s@/]+@")
_TOKEN = re.compile(r"\b(?:gh[pous]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})\b")


def redact_text(value: str) -> str:
    """Redact value-shaped secrets without hiding useful diagnostics."""

    value = _SECRET_VALUE.sub(lambda match: match.group(0).replace(match.group(1), "***REDACTED***"), value)
    value = _CONNECTION_SECRET.sub(lambda match: match.group(0).split("://", 1)[0] + "://***REDACTED***@", value)
    return _TOKEN.sub("***REDACTED***", value)


def read_json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DeploymentError(f"Invalid JSON file: {path}") from exc
    if not isinstance(payload, dict):
        raise DeploymentError(f"JSON document must be an object: {path}")
    return payload
