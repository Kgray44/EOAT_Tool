from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import fields, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, TypeVar

from core.atlas_models import (
    AtlasDataBundle,
    AtlasIndexes,
    AtlasSourceStatus,
    CompatibilityLink,
    DocumentationStatus,
    EOATRecord,
    MachineRecord,
    PhotoItem,
    PhotoSet,
    StandardReference,
    ToolRecord,
    WarningItem,
)


SCHEMA_VERSION = 1
T = TypeVar("T")


@contextmanager
def connect_cache_db(path: str | Path) -> Iterator[sqlite3.Connection]:
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    initialize_schema(conn)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def initialize_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS cache_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL,
            description TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS app_metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS bundle_cache (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            payload_json TEXT NOT NULL,
            refreshed_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS source_files (
            key TEXT PRIMARY KEY,
            source_path TEXT NOT NULL,
            copied_to TEXT NOT NULL DEFAULT '',
            exists_at_import INTEGER NOT NULL DEFAULT 0,
            size INTEGER NOT NULL DEFAULT 0,
            mtime_ns INTEGER NOT NULL DEFAULT 0,
            sha256 TEXT NOT NULL DEFAULT '',
            staged_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS import_runs (
            import_id TEXT PRIMARY KEY,
            started_at TEXT NOT NULL,
            completed_at TEXT NOT NULL,
            status TEXT NOT NULL,
            eoat_count INTEGER NOT NULL DEFAULT 0,
            tool_count INTEGER NOT NULL DEFAULT 0,
            machine_count INTEGER NOT NULL DEFAULT 0,
            metadata_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE IF NOT EXISTS eoats (
            eoat_id TEXT PRIMARY KEY,
            display_id TEXT NOT NULL,
            payload_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS tools (
            tool TEXT PRIMARY KEY,
            label TEXT NOT NULL,
            payload_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS machines (
            machine TEXT PRIMARY KEY,
            label TEXT NOT NULL,
            payload_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS compatibility (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            eoat_id TEXT NOT NULL DEFAULT '',
            machine TEXT NOT NULL DEFAULT '',
            tool TEXT NOT NULL DEFAULT '',
            part TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS photos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            eoat_id TEXT NOT NULL DEFAULT '',
            tool TEXT NOT NULL DEFAULT '',
            machine TEXT NOT NULL DEFAULT '',
            path TEXT NOT NULL,
            payload_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            path TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT '',
            payload_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS pending_updates (
            update_id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            field TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS event_outbox (
            event_id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            action TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS event_log (
            event_id TEXT PRIMARY KEY,
            event_timestamp TEXT NOT NULL,
            app_instance_id TEXT NOT NULL DEFAULT '',
            action TEXT NOT NULL,
            entity_type TEXT NOT NULL DEFAULT '',
            entity_id TEXT NOT NULL DEFAULT '',
            field TEXT NOT NULL DEFAULT '',
            payload_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sync_attempts (
            attempt_id TEXT PRIMARY KEY,
            update_id TEXT NOT NULL DEFAULT '',
            event_id TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL,
            started_at TEXT NOT NULL,
            completed_at TEXT NOT NULL DEFAULT '',
            message TEXT NOT NULL DEFAULT '',
            payload_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE IF NOT EXISTS conflicts (
            conflict_id TEXT PRIMARY KEY,
            update_id TEXT NOT NULL DEFAULT '',
            entity_type TEXT NOT NULL DEFAULT '',
            entity_id TEXT NOT NULL DEFAULT '',
            field TEXT NOT NULL DEFAULT '',
            base_value TEXT NOT NULL DEFAULT '',
            local_value TEXT NOT NULL DEFAULT '',
            workbook_value TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'open',
            detected_at TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_compatibility_eoat ON compatibility(eoat_id);
        CREATE INDEX IF NOT EXISTS idx_compatibility_machine ON compatibility(machine);
        CREATE INDEX IF NOT EXISTS idx_compatibility_tool ON compatibility(tool);
        CREATE INDEX IF NOT EXISTS idx_photos_eoat ON photos(eoat_id);
        CREATE INDEX IF NOT EXISTS idx_pending_updates_entity ON pending_updates(entity_type, entity_id);
        CREATE INDEX IF NOT EXISTS idx_event_outbox_status ON event_outbox(status);
        """
    )
    _ensure_column(conn, "source_files", "sha256", "TEXT NOT NULL DEFAULT ''")
    now = datetime.now().isoformat(timespec="seconds")
    conn.execute("INSERT OR REPLACE INTO cache_meta(key, value) VALUES('schema_version', ?)", (str(SCHEMA_VERSION),))
    conn.execute(
        "INSERT OR IGNORE INTO schema_migrations(version, applied_at, description) VALUES(?, ?, ?)",
        (SCHEMA_VERSION, now, "Initial Phase 1 local-first SQLite cache schema."),
    )
    conn.execute(
        "INSERT OR REPLACE INTO app_metadata(key, value, updated_at) VALUES('cache_schema_version', ?, ?)",
        (str(SCHEMA_VERSION), now),
    )


def write_bundle(
    conn: sqlite3.Connection,
    bundle: AtlasDataBundle,
    *,
    import_id: str,
    source_metadata: dict[str, dict[str, Any]],
    started_at: str,
) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    conn.execute("DELETE FROM bundle_cache")
    conn.execute("DELETE FROM source_files")
    conn.execute("DELETE FROM import_runs")
    conn.execute("DELETE FROM eoats")
    conn.execute("DELETE FROM tools")
    conn.execute("DELETE FROM machines")
    conn.execute("DELETE FROM compatibility")
    conn.execute("DELETE FROM photos")
    conn.execute("DELETE FROM documents")

    conn.execute(
        "INSERT INTO bundle_cache(id, payload_json, refreshed_at) VALUES(1, ?, ?)",
        (json.dumps(bundle.to_dict(), default=str), now),
    )
    for key, metadata in source_metadata.items():
        conn.execute(
            """
            INSERT OR REPLACE INTO source_files(key, source_path, copied_to, exists_at_import, size, mtime_ns, sha256, staged_at)
            VALUES(?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                key,
                str(metadata.get("source_path", "")),
                str(metadata.get("copied_to", "")),
                1 if metadata.get("exists_at_import") else 0,
                int(metadata.get("size") or 0),
                int(metadata.get("mtime_ns") or 0),
                str(metadata.get("sha256") or ""),
                str(metadata.get("staged_at") or now),
            ),
        )
    for eoat in bundle.eoats:
        conn.execute(
            "INSERT OR REPLACE INTO eoats(eoat_id, display_id, payload_json) VALUES(?, ?, ?)",
            (eoat.eoat_id, eoat.display_id, json.dumps(eoat.to_dict(), default=str)),
        )
        for tool in eoat.tools:
            for machine in eoat.machines:
                conn.execute(
                    "INSERT INTO compatibility(eoat_id, machine, tool, part, source) VALUES(?, ?, ?, ?, ?)",
                    (eoat.eoat_id, machine, tool, "", "EOAT inventory"),
                )
        for photo in (*eoat.photos.photos, *eoat.photos.indexed_photos):
            conn.execute(
                "INSERT INTO photos(eoat_id, tool, machine, path, payload_json) VALUES(?, ?, ?, ?, ?)",
                (photo.eoat_id or eoat.eoat_id, photo.tool, photo.machine, photo.path, json.dumps(photo.to_dict(), default=str)),
            )
    for tool in bundle.tools:
        conn.execute(
            "INSERT OR REPLACE INTO tools(tool, label, payload_json) VALUES(?, ?, ?)",
            (tool.tool, tool.label, json.dumps(tool.to_dict(), default=str)),
        )
    for machine in bundle.machines:
        conn.execute(
            "INSERT OR REPLACE INTO machines(machine, label, payload_json) VALUES(?, ?, ?)",
            (machine.machine, machine.label, json.dumps(machine.to_dict(), default=str)),
        )
    for standard in bundle.standards:
        conn.execute(
            "INSERT INTO documents(title, path, category, payload_json) VALUES(?, ?, ?, ?)",
            (standard.title, standard.path, standard.category, json.dumps(standard.to_dict(), default=str)),
        )
    conn.execute(
        """
        INSERT OR REPLACE INTO import_runs(import_id, started_at, completed_at, status, eoat_count, tool_count, machine_count, metadata_json)
        VALUES(?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            import_id,
            started_at,
            now,
            "success",
            len(bundle.eoats),
            len(bundle.tools),
            len(bundle.machines),
            json.dumps({"source_files": source_metadata}, default=str),
        ),
    )
    conn.execute("INSERT OR REPLACE INTO cache_meta(key, value) VALUES('last_refresh', ?)", (now,))


def read_bundle(conn: sqlite3.Connection) -> AtlasDataBundle | None:
    row = conn.execute("SELECT payload_json FROM bundle_cache WHERE id = 1").fetchone()
    if not row:
        return None
    return bundle_from_dict(json.loads(row["payload_json"]))


def cache_metadata(conn: sqlite3.Connection) -> dict[str, Any]:
    source_rows = conn.execute("SELECT * FROM source_files ORDER BY key").fetchall()
    import_rows = conn.execute("SELECT * FROM import_runs ORDER BY completed_at DESC").fetchall()
    meta_rows = conn.execute("SELECT key, value FROM cache_meta").fetchall()
    return {
        "meta": {row["key"]: row["value"] for row in meta_rows},
        "source_files": {
            row["key"]: {
                "source_path": row["source_path"],
                "copied_to": row["copied_to"],
                "exists_at_import": bool(row["exists_at_import"]),
                "size": row["size"],
                "mtime_ns": row["mtime_ns"],
                "sha256": row["sha256"],
                "staged_at": row["staged_at"],
            }
            for row in source_rows
        },
        "import_runs": [dict(row) for row in import_rows],
    }


def bundle_from_dict(payload: dict[str, Any]) -> AtlasDataBundle:
    return AtlasDataBundle(
        project_root=str(payload.get("project_root", "")),
        loaded_at=str(payload.get("loaded_at", "")),
        source_statuses=tuple(_dataclass_from_dict(AtlasSourceStatus, item) for item in payload.get("source_statuses", ())),
        eoats=tuple(_eoat_from_dict(item) for item in payload.get("eoats", ())),
        machines=tuple(_machine_from_dict(item) for item in payload.get("machines", ())),
        tools=tuple(_tool_from_dict(item) for item in payload.get("tools", ())),
        press_capacity_rows=tuple(dict(item) for item in payload.get("press_capacity_rows", ())),
        standards=tuple(_dataclass_from_dict(StandardReference, item) for item in payload.get("standards", ())),
        warnings=tuple(_dataclass_from_dict(WarningItem, item) for item in payload.get("warnings", ())),
        indexes=_indexes_from_dict(payload.get("indexes") or {}),
        metrics=dict(payload.get("metrics") or {}),
    )


def _eoat_from_dict(payload: dict[str, Any]) -> EOATRecord:
    data = _filtered_kwargs(EOATRecord, payload)
    data["audit_ids"] = tuple(data.get("audit_ids") or ())
    data["tools"] = tuple(data.get("tools") or ())
    data["molds"] = tuple(data.get("molds") or ())
    data["parts"] = tuple(data.get("parts") or ())
    data["machines"] = tuple(data.get("machines") or ())
    data["robot_types"] = tuple(data.get("robot_types") or ())
    data["robot_models"] = tuple(data.get("robot_models") or ())
    data["documentation"] = _documentation_from_dict(data.get("documentation") or {})
    data["photos"] = _photo_set_from_dict(data.get("photos") or {})
    data["warnings"] = tuple(_dataclass_from_dict(WarningItem, item) for item in data.get("warnings") or ())
    data["standards"] = tuple(_dataclass_from_dict(StandardReference, item) for item in data.get("standards") or ())
    data["source_rows"] = tuple(dict(item) for item in data.get("source_rows") or ())
    return EOATRecord(**data)


def _machine_from_dict(payload: dict[str, Any]) -> MachineRecord:
    data = _filtered_kwargs(MachineRecord, payload)
    for key in ("compatible_eoats", "compatible_tools", "compatible_parts"):
        data[key] = tuple(data.get(key) or ())
    data["warnings"] = tuple(_dataclass_from_dict(WarningItem, item) for item in data.get("warnings") or ())
    data["source_rows"] = tuple(dict(item) for item in data.get("source_rows") or ())
    return MachineRecord(**data)


def _tool_from_dict(payload: dict[str, Any]) -> ToolRecord:
    data = _filtered_kwargs(ToolRecord, payload)
    for key in ("molds", "parts", "compatible_eoats", "compatible_machines"):
        data[key] = tuple(data.get(key) or ())
    data["warnings"] = tuple(_dataclass_from_dict(WarningItem, item) for item in data.get("warnings") or ())
    data["source_rows"] = tuple(dict(item) for item in data.get("source_rows") or ())
    return ToolRecord(**data)


def _documentation_from_dict(payload: dict[str, Any]) -> DocumentationStatus:
    data = _filtered_kwargs(DocumentationStatus, payload)
    for key in ("present_fields", "missing_fields", "critical_missing_fields"):
        data[key] = tuple(data.get(key) or ())
    data["checklist"] = tuple(tuple(item) for item in data.get("checklist") or ())
    return DocumentationStatus(**data)


def _photo_set_from_dict(payload: dict[str, Any]) -> PhotoSet:
    data = _filtered_kwargs(PhotoSet, payload)
    data["photos"] = tuple(_dataclass_from_dict(PhotoItem, item) for item in data.get("photos") or ())
    data["indexed_photos"] = tuple(_dataclass_from_dict(PhotoItem, item) for item in data.get("indexed_photos") or ())
    data["missing_categories"] = tuple(data.get("missing_categories") or ())
    return PhotoSet(**data)


def _indexes_from_dict(payload: dict[str, Any]) -> AtlasIndexes:
    data = _filtered_kwargs(AtlasIndexes, payload)
    tuple_keys = {
        "eoats_by_tool",
        "eoats_by_machine",
        "machines_by_tool",
        "machines_by_eoat",
        "tools_by_machine",
        "photos_by_eoat",
        "photos_by_tool",
    }
    for key in tuple_keys:
        data[key] = {str(item_key): tuple(item_value or ()) for item_key, item_value in dict(data.get(key) or {}).items()}
    for key in ("warnings_by_eoat", "warnings_by_machine"):
        data[key] = {
            str(item_key): tuple(_dataclass_from_dict(WarningItem, item) for item in (item_value or ()))
            for item_key, item_value in dict(data.get(key) or {}).items()
        }
    data["documentation_status_by_eoat"] = {
        str(item_key): _documentation_from_dict(item_value or {})
        for item_key, item_value in dict(data.get("documentation_status_by_eoat") or {}).items()
    }
    return AtlasIndexes(**data)


def _dataclass_from_dict(cls: type[T], payload: dict[str, Any]) -> T:
    if is_dataclass(cls):
        return cls(**_filtered_kwargs(cls, dict(payload or {})))  # type: ignore[misc]
    raise TypeError(cls)


def _filtered_kwargs(cls: type[Any], payload: dict[str, Any]) -> dict[str, Any]:
    names = {field.name for field in fields(cls)}
    return {key: value for key, value in dict(payload or {}).items() if key in names}


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
