from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.paths import resolve_project_paths
from core.safe_files import ensure_directory

HISTORY_FILE_NAME = "audit_history.jsonl"


@dataclass(frozen=True)
class AuditHistoryRecord:
    timestamp: str
    audit_id: str
    event_type: str
    changed_fields: list[str]
    old_values: dict[str, str] = field(default_factory=dict)
    new_values: dict[str, str] = field(default_factory=dict)
    source: str = "audit_entry_save"
    files_modified: list[str] = field(default_factory=list)


def audit_history_dir(project_root: str | Path) -> Path:
    return resolve_project_paths(project_root).project_admin / "history"


def audit_history_path(project_root: str | Path) -> Path:
    return audit_history_dir(project_root) / HISTORY_FILE_NAME


def normalize_history_value(value: Any) -> str:
    return "" if value is None else str(value)


def changed_audit_fields(before: dict[str, Any] | None, after: dict[str, Any] | None) -> list[str]:
    before = before or {}
    after = after or {}
    keys = set(before) | set(after)
    changed = [
        key
        for key in keys
        if normalize_history_value(before.get(key)) != normalize_history_value(after.get(key))
    ]
    return sorted(changed)


def build_audit_history_record(
    audit_id: str,
    event_type: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    *,
    source: str = "audit_entry_save",
    files_modified: list[str] | None = None,
) -> AuditHistoryRecord:
    fields = changed_audit_fields(before, after)
    before = before or {}
    after = after or {}
    return AuditHistoryRecord(
        timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        audit_id=str(audit_id or ""),
        event_type=event_type,
        changed_fields=fields,
        old_values={field: normalize_history_value(before.get(field)) for field in fields},
        new_values={field: normalize_history_value(after.get(field)) for field in fields},
        source=source,
        files_modified=list(files_modified or []),
    )


def append_audit_history(
    project_root: str | Path,
    audit_id: str,
    event_type: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    *,
    source: str = "audit_entry_save",
    files_modified: list[str] | None = None,
) -> Path:
    path = audit_history_path(project_root)
    ensure_directory(path.parent)
    record = build_audit_history_record(
        audit_id,
        event_type,
        before,
        after,
        source=source,
        files_modified=files_modified,
    )
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(asdict(record), sort_keys=True) + "\n")
    return path


def read_audit_history(project_root: str | Path) -> list[dict[str, Any]]:
    path = audit_history_path(project_root)
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            records.append(parsed)
    return records
