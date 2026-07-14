from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .pending_updates import apply_pending_overlay, pending_updates_for_entity
from .runtime_paths import get_runtime_paths
from .sqlite_store import cache_metadata, connect_cache_db


class SQLiteRepository:
    table_name = ""
    key_column = ""
    entity_type = ""

    def __init__(self, db_path: str | Path | None = None):
        self.db_path = Path(db_path) if db_path else get_runtime_paths().db_path
        self.runtime = get_runtime_paths()

    def all(self) -> list[dict[str, Any]]:
        with connect_cache_db(self.db_path) as conn:
            rows = conn.execute(f"SELECT payload_json FROM {self.table_name} ORDER BY {self.key_column}").fetchall()
        return [json.loads(row["payload_json"]) for row in rows]

    def get(self, key: str) -> dict[str, Any] | None:
        with connect_cache_db(self.db_path) as conn:
            row = conn.execute(
                f"SELECT payload_json FROM {self.table_name} WHERE {self.key_column} = ?",
                (key,),
            ).fetchone()
        return json.loads(row["payload_json"]) if row else None

    def effective_all(self, pending_dir: str | Path | None = None) -> list[dict[str, Any]]:
        return [self.effective_record(record, pending_dir=pending_dir) for record in self.all()]

    def effective_get(self, key: str, pending_dir: str | Path | None = None) -> dict[str, Any] | None:
        return self.effective_record(self.get(key), pending_dir=pending_dir)

    def effective_record(self, record: dict[str, Any] | None, pending_dir: str | Path | None = None) -> dict[str, Any] | None:
        if record is None:
            return None
        entity_type = self.entity_type
        entity_id = _entity_id(record, self.key_column)
        updates = pending_updates_for_entity(
            pending_dir or self.runtime.pending_updates_dir,
            entity_type=entity_type,
            entity_id=entity_id,
        )
        return apply_pending_overlay(record, updates)


class EOATRepository(SQLiteRepository):
    table_name = "eoats"
    key_column = "eoat_id"
    entity_type = "eoat"


class ToolRepository(SQLiteRepository):
    table_name = "tools"
    key_column = "tool"
    entity_type = "tool"


class MachineRepository(SQLiteRepository):
    table_name = "machines"
    key_column = "machine"
    entity_type = "machine"


class CompatibilityRepository:
    def __init__(self, db_path: str | Path | None = None):
        self.db_path = Path(db_path) if db_path else get_runtime_paths().db_path

    def all(self) -> list[dict[str, Any]]:
        with connect_cache_db(self.db_path) as conn:
            rows = conn.execute("SELECT eoat_id, machine, tool, part, source FROM compatibility ORDER BY machine, tool, eoat_id").fetchall()
        return [dict(row) for row in rows]


class PhotoRepository:
    def __init__(self, db_path: str | Path | None = None):
        self.db_path = Path(db_path) if db_path else get_runtime_paths().db_path

    def all(self) -> list[dict[str, Any]]:
        with connect_cache_db(self.db_path) as conn:
            rows = conn.execute("SELECT payload_json FROM photos ORDER BY eoat_id, path").fetchall()
        return [json.loads(row["payload_json"]) for row in rows]


class DocumentRepository:
    def __init__(self, db_path: str | Path | None = None):
        self.db_path = Path(db_path) if db_path else get_runtime_paths().db_path

    def all(self) -> list[dict[str, Any]]:
        with connect_cache_db(self.db_path) as conn:
            rows = conn.execute("SELECT payload_json FROM documents ORDER BY category, title").fetchall()
        return [json.loads(row["payload_json"]) for row in rows]


class CacheMetadataRepository:
    def __init__(self, db_path: str | Path | None = None):
        self.db_path = Path(db_path) if db_path else get_runtime_paths().db_path

    def summary(self) -> dict[str, Any]:
        with connect_cache_db(self.db_path) as conn:
            return cache_metadata(conn)


def _entity_id(record: dict[str, Any], key_column: str) -> str:
    return str(record.get(key_column) or record.get("id") or record.get("display_id") or "")
