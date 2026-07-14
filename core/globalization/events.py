from __future__ import annotations

import json
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from .config import AtlasGlobalConfig
from .install_identity import load_or_create_install_identity
from .runtime_paths import AtlasRuntimePaths, atomic_write_json, ensure_runtime_layout

EVENT_SCHEMA_VERSION = 1
REQUIRED_EVENT_FIELDS = {
    "event_id",
    "event_schema_version",
    "event_type",
    "created_at",
    "app_name",
    "app_version",
    "release_id",
    "install_id",
    "app_instance_id",
    "machine_name",
    "windows_user",
    "environment",
    "sync_attempt_id",
    "pending_update_ids",
    "field_changes",
    "validation_result",
    "conflict_result",
    "write_result",
}


class EventOutbox:
    def __init__(self, runtime: AtlasRuntimePaths, config: AtlasGlobalConfig):
        self.runtime = ensure_runtime_layout(runtime)
        self.config = config
        self.identity = load_or_create_install_identity(self.runtime)

    def create_event(
        self,
        *,
        action: str = "",
        event_type: str = "",
        entity_type: str = "",
        entity_id: str = "",
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = datetime.now().isoformat(timespec="milliseconds")
        data = dict(payload or {})
        event_id = str(data.get("event_id") or uuid4().hex)
        pending_update_ids = data.get("pending_update_ids") or data.get("pending_update_id") or []
        if isinstance(pending_update_ids, str):
            pending_update_ids = [pending_update_ids]
        event = {
            "event_id": event_id,
            "event_schema_version": self.config.event_schema_version or EVENT_SCHEMA_VERSION,
            "event_type": event_type or action or "atlas_event",
            "status": "queued",
            "created_at": now,
            "updated_at": now,
            "app_name": self.config.product_name,
            "app_version": self.config.app_version,
            "release_id": self.config.release_id,
            "build_id": self.config.build_id,
            "git_commit": self.config.git_commit,
            "install_id": self.config.install_id or self.identity.install_id,
            "app_instance_id": self.config.app_instance_id,
            "launch_session_id": str(data.get("launch_session_id") or ""),
            "machine_name": self.config.machine_name or self.config.computer_name,
            "computer_name": self.config.computer_name,
            "windows_user": self.config.windows_user,
            "installed_by": self.config.installed_by,
            "environment": self.config.environment,
            "action": action or event_type or "atlas_event",
            "source_action": str(data.get("source_action") or data.get("source_view") or ""),
            "entity_type": entity_type,
            "entity_id": entity_id,
            "workbook_path": str(data.get("workbook_path") or ""),
            "workbook_id": str(data.get("workbook_id") or ""),
            "workbook_fingerprint_before": data.get("workbook_fingerprint_before") or data.get("source_workbook_fingerprint") or {},
            "workbook_fingerprint_after": data.get("workbook_fingerprint_after") or {},
            "workbook_modified_time_before": str(data.get("workbook_modified_time_before") or ""),
            "workbook_modified_time_after": str(data.get("workbook_modified_time_after") or ""),
            "lock_id": str(data.get("lock_id") or ""),
            "sync_attempt_id": str(data.get("sync_attempt_id") or ""),
            "pending_update_ids": [str(item) for item in pending_update_ids],
            "field_changes": data.get("field_changes") or [],
            "expected_original_values": data.get("expected_original_values") or {},
            "actual_workbook_values_before_write": data.get("actual_workbook_values_before_write") or {},
            "proposed_values": data.get("proposed_values") or {},
            "values_written": data.get("values_written") or {},
            "validation_result": data.get("validation_result") or {"status": "not_run"},
            "conflict_result": data.get("conflict_result") or {"status": "not_checked"},
            "write_result": data.get("write_result") or {"status": "not_run"},
            "error_type": str(data.get("error_type") or ""),
            "error_message": str(data.get("error_message") or ""),
            "backup_path": str(data.get("backup_path") or ""),
            "runtime_root": str(self.runtime.runtime_root),
            "safe_diagnostic_path": str(data.get("safe_diagnostic_path") or self.runtime.logs_dir),
            "payload": data,
            "source_workbook_fingerprint": data.get("workbook_fingerprint_before")
            or data.get("source_workbook_fingerprint")
            or {},
            "sync_status": "queued",
            "retry_count": 0,
            "last_attempt": "",
            "last_error": "",
            "conflict_status": str((data.get("conflict_result") or {}).get("status") or "none")
            if isinstance(data.get("conflict_result"), dict)
            else "none",
        }
        validate_event_payload(event)
        atomic_write_json(self.runtime.event_outbox_dir / event_filename(event), event)
        return event

    def list_events(self) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for path in sorted(self.runtime.event_outbox_dir.glob("*.json")):
            try:
                events.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue
        return events


class GlobalEventWriter:
    def __init__(self, config: AtlasGlobalConfig):
        self.config = config

    def deliver_sandbox_event(self, event_path: str | Path, sandbox_dir: str | Path) -> Path:
        source = Path(event_path)
        target_dir = Path(sandbox_dir)
        if self._is_live_event_log_target(target_dir):
            raise PermissionError("Refusing to write sandbox event to the configured live event log path.")
        target_dir.mkdir(parents=True, exist_ok=True)
        payload = json.loads(source.read_text(encoding="utf-8"))
        payload["status"] = "delivered_to_sandbox"
        payload["updated_at"] = datetime.now().isoformat(timespec="seconds")
        target = target_dir / source.name
        atomic_write_json(target, payload)
        return target

    def copy_to_live_event_log(self, event_path: str | Path) -> Path:
        if not self.config.writes_enabled():
            raise PermissionError("Global event delivery is disabled in development mode.")
        if not str(self.config.event_log_path or "").strip():
            raise PermissionError("No live event log path is configured.")
        target_dir = Path(self.config.event_log_path)
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / Path(event_path).name
        shutil.copy2(event_path, target)
        return target

    def _is_live_event_log_target(self, target_dir: Path) -> bool:
        configured = str(self.config.event_log_path or "").strip()
        if not configured:
            return False
        try:
            return target_dir.resolve(strict=False) == Path(configured).resolve(strict=False)
        except OSError:
            return False


def event_filename(event: dict[str, Any]) -> str:
    created_at = str(event.get("created_at") or datetime.now().isoformat(timespec="milliseconds"))
    try:
        parsed = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError:
        parsed = datetime.now()
    stamp = parsed.strftime("%Y%m%d_%H%M%S")
    millis = f"{int(parsed.microsecond / 1000):03d}"
    machine = _safe_filename_token(str(event.get("machine_name") or event.get("computer_name") or "machine"))
    install_short = _safe_filename_token(str(event.get("install_id") or "install"))[:8]
    event_id = _safe_filename_token(str(event.get("event_id") or uuid4().hex))
    return f"{stamp}_{millis}_{machine}_{install_short}_{event_id}.json"


def validate_event_payload(event: dict[str, Any]) -> None:
    missing = sorted(field for field in REQUIRED_EVENT_FIELDS if field not in event)
    if missing:
        raise ValueError(f"Event payload is missing required field(s): {', '.join(missing)}")
    if int(event.get("event_schema_version") or 0) < 1:
        raise ValueError("Event payload has an invalid event_schema_version.")
    if not str(event.get("event_id") or "").strip():
        raise ValueError("Event payload is missing event_id.")


def atomic_write_event_json(path: str | Path, event: dict[str, Any]) -> Path:
    validate_event_payload(event)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(event, stream, indent=2, sort_keys=True, default=str)
            stream.write("\n")
        Path(tmp_name).replace(target)
    except Exception:
        Path(tmp_name).unlink(missing_ok=True)
        raise
    return target


def _safe_filename_token(value: str) -> str:
    token = "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in value.strip())
    return token.strip("-_") or "unknown"


__all__ = [
    "EVENT_SCHEMA_VERSION",
    "EventOutbox",
    "GlobalEventWriter",
    "atomic_write_event_json",
    "event_filename",
    "validate_event_payload",
]
