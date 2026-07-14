from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from .config import AtlasGlobalConfig
from .install_identity import load_or_create_install_identity
from .runtime_paths import AtlasRuntimePaths, atomic_write_json, ensure_runtime_layout


class PendingUpdateStore:
    def __init__(self, runtime: AtlasRuntimePaths, config: AtlasGlobalConfig):
        self.runtime = ensure_runtime_layout(runtime)
        self.config = config
        self.identity = load_or_create_install_identity(self.runtime)

    def create_update(
        self,
        *,
        entity_type: str,
        entity_id: str,
        field: str = "",
        field_name: str = "",
        original_value: Any = None,
        expected_original_value: Any = None,
        proposed_value: Any = None,
        reason: str = "",
        source_view: str = "",
        source_action: str = "",
        validation_status: str = "valid",
    ) -> dict[str, Any]:
        now = datetime.now().isoformat(timespec="seconds")
        event_id = uuid4().hex
        pending_update_id = uuid4().hex
        resolved_field = str(field_name or field or "").strip()
        expected_value = expected_original_value if expected_original_value is not None else original_value
        update = {
            "pending_update_id": pending_update_id,
            "update_id": pending_update_id,
            "event_id": event_id,
            "status": "pending",
            "validation_status": validation_status,
            "event_log_status": "event_pending",
            "sync_status": "not_started",
            "workbook_sync_status": "not_started",
            "retry_count": 0,
            "last_attempt": "",
            "last_error": "",
            "conflict_status": "none",
            "resolution_status": "unresolved",
            "entity_type": entity_type,
            "entity_id": entity_id,
            "field_name": resolved_field,
            "field": resolved_field,
            "expected_original_value": expected_value,
            "original_value": expected_value,
            "proposed_value": proposed_value,
            "reason": reason,
            "source_view": source_view,
            "source_action": source_action,
            "source_workbook_fingerprint": "",
            "created_at": now,
            "updated_at": now,
            "app_install_identity_snapshot": self.identity.to_dict(),
            "install_id": self.config.install_id or self.identity.install_id,
            "app_instance_id": self.config.app_instance_id,
            "app_version": self.config.app_version,
            "release_id": self.config.release_id,
            "build_id": self.config.build_id,
            "git_commit": self.config.git_commit,
            "computer_name": self.config.computer_name,
            "machine_name": self.config.machine_name,
            "windows_user": self.config.windows_user,
            "installed_by": self.config.installed_by,
            "environment": self.config.environment,
        }
        atomic_write_json(self.runtime.pending_updates_dir / f"{pending_update_id}.json", update)
        return update

    def list_updates(self) -> list[dict[str, Any]]:
        return [_read_json(path) for path in sorted(self.runtime.pending_updates_dir.glob("*.json"))]

    def list_active_updates(self) -> list[dict[str, Any]]:
        return [update for update in self.list_updates() if update_is_active(update)]

    def get_update(self, update_id: str) -> dict[str, Any] | None:
        path = self.runtime.pending_updates_dir / f"{update_id}.json"
        payload = _read_json(path)
        return payload or None

    def export_updates(self, export_path: str | Path) -> Path:
        target = Path(export_path)
        atomic_write_json(
            target,
            {
                "exported_at": datetime.now().isoformat(timespec="seconds"),
                "install_id": self.config.install_id or self.identity.install_id,
                "app_instance_id": self.config.app_instance_id,
                "computer_name": self.config.computer_name,
                "machine_name": self.config.machine_name,
                "windows_user": self.config.windows_user,
                "app_version": self.config.app_version,
                "release_id": self.config.release_id,
                "updates": self.list_updates(),
            },
        )
        return target

    def set_status(self, update_id: str, status: str) -> dict[str, Any]:
        path = self.runtime.pending_updates_dir / f"{update_id}.json"
        payload = _read_json(path)
        payload["status"] = status
        payload["updated_at"] = datetime.now().isoformat(timespec="seconds")
        atomic_write_json(path, payload)
        return payload

    def set_sync_status(
        self,
        update_id: str,
        *,
        sync_status: str,
        status: str | None = None,
        conflict_status: str | None = None,
        last_error: str = "",
        sync_attempt_id: str = "",
    ) -> dict[str, Any]:
        path = self.runtime.pending_updates_dir / f"{update_id}.json"
        payload = _read_json(path)
        if not payload:
            raise FileNotFoundError(path)
        now = datetime.now().isoformat(timespec="seconds")
        payload["sync_status"] = sync_status
        payload["workbook_sync_status"] = sync_status
        if status is not None:
            payload["status"] = status
        if conflict_status is not None:
            payload["conflict_status"] = conflict_status
        if last_error:
            payload["last_error"] = last_error
        if sync_attempt_id:
            payload["sync_attempt_id"] = sync_attempt_id
        payload["last_attempt"] = now
        payload["updated_at"] = now
        atomic_write_json(path, payload)
        return payload

    def clear_after_success(self, update_id: str, *, sync_attempt_id: str = "") -> dict[str, Any]:
        return self.set_sync_status(
            update_id,
            sync_status="applied",
            status="applied",
            conflict_status="none",
            sync_attempt_id=sync_attempt_id,
        )


def reindex_pending_updates(conn: sqlite3.Connection, pending_dir: str | Path) -> int:
    conn.execute("DELETE FROM pending_updates")
    count = 0
    for path in sorted(Path(pending_dir).glob("*.json")):
        payload = _read_json(path)
        if not payload:
            continue
        conn.execute(
            """
            INSERT OR REPLACE INTO pending_updates(update_id, status, entity_type, entity_id, field, payload_json, updated_at)
            VALUES(?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(payload.get("update_id") or path.stem),
                str(payload.get("status") or "pending"),
                str(payload.get("entity_type") or ""),
                str(payload.get("entity_id") or ""),
                str(payload.get("field_name") or payload.get("field") or ""),
                json.dumps(payload, default=str),
                str(payload.get("updated_at") or payload.get("created_at") or ""),
            ),
        )
        count += 1
    return count


def pending_updates_for_entity(
    pending_dir: str | Path,
    *,
    entity_type: str,
    entity_id: str,
    active_only: bool = True,
) -> list[dict[str, Any]]:
    target_type = _normalize_entity_type(entity_type)
    target_id = _normalize_entity_id(entity_id)
    updates: list[dict[str, Any]] = []
    for path in sorted(Path(pending_dir).glob("*.json")):
        payload = _read_json(path)
        if not payload:
            continue
        if active_only and not update_is_active(payload):
            continue
        if _normalize_entity_type(payload.get("entity_type")) != target_type:
            continue
        if _normalize_entity_id(payload.get("entity_id")) != target_id:
            continue
        updates.append(payload)
    return updates


def update_is_active(update: dict[str, Any]) -> bool:
    status = str(update.get("status") or "pending").strip().casefold()
    resolution = str(update.get("resolution_status") or "").strip().casefold()
    return status not in {"applied", "cancelled", "canceled", "discarded", "rejected"} and resolution not in {
        "resolved",
        "discarded",
    }


def apply_pending_overlay(base_record: dict[str, Any] | None, updates: list[dict[str, Any]]) -> dict[str, Any] | None:
    if base_record is None:
        return None
    effective = dict(base_record)
    active_updates = [update for update in updates if update_is_active(update)]
    pending_fields: list[str] = []
    pending_update_ids: list[str] = []
    field_updates: dict[str, list[dict[str, Any]]] = {}
    for update in active_updates:
        field_name = str(update.get("field") or "").strip()
        field_name = str(update.get("field_name") or field_name).strip()
        if not field_name:
            continue
        field_key = _record_field_key(effective, field_name)
        if not field_key:
            field_key = _snake_name(field_name)
        field_updates.setdefault(field_key, []).append(update)
        pending_fields.append(field_key)
        pending_update_ids.append(str(update.get("update_id") or ""))
        effective[field_key] = update.get("proposed_value")
    conflicts = detect_pending_update_conflicts(active_updates)
    effective["_pending_status"] = "conflict" if conflicts else ("pending" if active_updates else "clean")
    effective["_pending_fields"] = tuple(dict.fromkeys(pending_fields))
    effective["_pending_update_ids"] = tuple(update_id for update_id in dict.fromkeys(pending_update_ids) if update_id)
    effective["_pending_updates"] = tuple(active_updates)
    effective["_pending_conflicts"] = tuple(conflicts)
    effective["_pending_field_updates"] = {key: tuple(value) for key, value in field_updates.items()}
    return effective


def detect_pending_update_conflicts(updates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for update in updates:
        if not update_is_active(update):
            continue
        key = (
            _normalize_entity_type(update.get("entity_type")),
            _normalize_entity_id(update.get("entity_id")),
            _normalize_field(update.get("field_name") or update.get("field")),
        )
        if not all(key):
            continue
        grouped.setdefault(key, []).append(update)
    conflicts: list[dict[str, Any]] = []
    for (entity_type, entity_id, field), items in grouped.items():
        proposed_values = {_value_key(item.get("proposed_value")) for item in items}
        if len(proposed_values) <= 1:
            continue
        conflicts.append(
            {
                "conflict_id": f"{entity_type}:{entity_id}:{field}",
                "entity_type": entity_type,
                "entity_id": entity_id,
                "field": field,
                "status": "open",
                "detected_at": datetime.now().isoformat(timespec="seconds"),
                "update_ids": [str(item.get("update_id") or "") for item in items],
                "proposed_values": [item.get("proposed_value") for item in items],
            }
        )
    return conflicts


def _read_json(path: str | Path) -> dict[str, Any]:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _record_field_key(record: dict[str, Any], field_name: str) -> str:
    if field_name in record:
        return field_name
    normalized = _normalize_field(field_name)
    for key in record:
        if _normalize_field(key) == normalized:
            return str(key)
    return ""


def _normalize_entity_type(value: Any) -> str:
    return str(value or "").strip().casefold()


def _normalize_entity_id(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


def _normalize_field(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().casefold())


def _snake_name(value: str) -> str:
    name = re.sub(r"[^a-zA-Z0-9]+", "_", str(value or "").strip()).strip("_").casefold()
    return name or "pending_value"


def _value_key(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str)
