from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .exceptions import CacheUnavailableError
from .models import CacheStatus

CACHE_SCHEMA_VERSION = "4"
ENTITY_TABLES = {
    "eoats": "business_identifier",
    "machines": "machine_number",
    "tools": "business_identifier",
    "documents": "document_uuid",
    "photos": "document_uuid",
}


class CacheRepository:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def _connect(self, path: Path | None = None) -> sqlite3.Connection:
        target = path or self.path
        target.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(target, timeout=15)
        connection.row_factory = sqlite3.Row
        return connection

    def initialize(self, path: Path | None = None) -> None:
        with closing(self._connect(path)) as connection:
            connection.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS cache_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS cached_entities (entity_type TEXT NOT NULL, identifier TEXT NOT NULL, payload_json TEXT NOT NULL, PRIMARY KEY(entity_type, identifier));
                CREATE TABLE IF NOT EXISTS cached_lookups (lookup_type TEXT NOT NULL, code TEXT NOT NULL, payload_json TEXT NOT NULL, PRIMARY KEY(lookup_type, code));
                CREATE TABLE IF NOT EXISTS cached_changes (cursor INTEGER PRIMARY KEY, payload_json TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS cached_eoat_history (
                    eoat_identifier TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    occurred_at TEXT,
                    payload_json TEXT NOT NULL,
                    PRIMARY KEY(eoat_identifier, event_id)
                );
                CREATE TABLE IF NOT EXISTS cached_document_links (
                    document_identifier TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    entity_identifier TEXT NOT NULL,
                    relationship_type TEXT NOT NULL,
                    is_photo INTEGER NOT NULL DEFAULT 0,
                    is_profile_photo INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(document_identifier, entity_type, entity_identifier, relationship_type)
                );
                CREATE INDEX IF NOT EXISTS ix_cached_document_links_entity
                    ON cached_document_links(entity_type, entity_identifier, is_photo);
                CREATE INDEX IF NOT EXISTS ix_cached_eoat_history_timeline
                    ON cached_eoat_history(eoat_identifier, occurred_at DESC, event_id DESC);
                CREATE VIRTUAL TABLE IF NOT EXISTS search_index USING fts5(entity_type, identifier, text_content);
            """)
            created = datetime.now(timezone.utc).isoformat()
            defaults = {
                "cache_schema_version": CACHE_SCHEMA_VERSION,
                "api_version": "",
                "server_schema_revision": "",
                "last_successful_sync_at": "",
                "last_full_refresh_at": "",
                "last_change_cursor": "0",
                "server_revision": "",
                "data_revision": "",
                "data_last_modified_at": "",
                "last_import_at": "",
                "last_import_source": "",
                "cache_created_at": created,
            }
            connection.executemany("INSERT OR IGNORE INTO cache_metadata(key,value) VALUES(?,?)", defaults.items())
            connection.commit()

    def metadata(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        with closing(self._connect()) as connection:
            return {row["key"]: row["value"] for row in connection.execute("SELECT key,value FROM cache_metadata")}

    def _put_metadata(self, connection: sqlite3.Connection, values: dict[str, Any]) -> None:
        connection.executemany(
            "INSERT INTO cache_metadata(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            [(key, str(value)) for key, value in values.items()],
        )

    def update_diagnostics(self, values: dict[str, Any]) -> None:
        if not self.path.exists():
            return
        with closing(self._connect()) as connection:
            self._put_metadata(connection, values)
            connection.commit()

    def build_snapshot(self, snapshot: dict[str, Any], destination: Path) -> None:
        if destination.exists():
            destination.unlink()
        self.initialize(destination)
        with closing(self._connect(destination)) as connection:
            connection.execute("BEGIN IMMEDIATE")
            for entity_type, identifier_field in ENTITY_TABLES.items():
                for payload in snapshot.get(entity_type, []):
                    identifier = str(payload.get(identifier_field, ""))
                    if entity_type == "machines" and identifier:
                        identifier = f"{payload.get('plant_code', '')}::{identifier}"
                    if not identifier:
                        raise CacheUnavailableError(f"Snapshot {entity_type} record has no {identifier_field}.")
                    connection.execute(
                        "INSERT INTO cached_entities(entity_type,identifier,payload_json) VALUES(?,?,?)",
                        (entity_type, identifier, json.dumps(payload, ensure_ascii=False)),
                    )
                    if entity_type in {"documents", "photos"}:
                        for relationship in payload.get("related_entities", []):
                            linked_type = str(relationship.get("relationship_type") or "").strip().casefold()
                            linked_identifier = str(relationship.get("identifier") or "").strip()
                            if not linked_type or not linked_identifier:
                                continue
                            connection.execute(
                                "INSERT OR REPLACE INTO cached_document_links(document_identifier,entity_type,entity_identifier,relationship_type,is_photo,is_profile_photo) VALUES(?,?,?,?,?,?)",
                                (
                                    identifier,
                                    linked_type,
                                    linked_identifier,
                                    linked_type,
                                    int(entity_type == "photos"),
                                    int(bool(payload.get("is_profile_photo"))),
                                ),
                            )
                    content = " ".join(str(value) for value in payload.values() if isinstance(value, str))
                    connection.execute(
                        "INSERT INTO search_index(entity_type,identifier,text_content) VALUES(?,?,?)",
                        (entity_type, identifier, content),
                    )
            for lookup_type, values in snapshot.get("lookups", {}).items():
                for payload in values:
                    connection.execute(
                        "INSERT INTO cached_lookups(lookup_type,code,payload_json) VALUES(?,?,?)",
                        (lookup_type, payload["code"], json.dumps(payload, ensure_ascii=False)),
                    )
            for payload in snapshot.get("eoat_history", []):
                identifier = str(payload.get("eoat_identifier") or "").strip()
                event_id = str(payload.get("event_id") or "").strip()
                if not identifier or not event_id:
                    raise CacheUnavailableError("Snapshot history record has no EOAT identifier or event ID.")
                connection.execute(
                    "INSERT INTO cached_eoat_history(eoat_identifier,event_id,occurred_at,payload_json) VALUES(?,?,?,?)",
                    (identifier, event_id, payload.get("occurred_at"), json.dumps(payload, ensure_ascii=False)),
                )
            now = datetime.now(timezone.utc).isoformat()
            self._put_metadata(
                connection,
                {
                    "api_version": snapshot.get("api_version", ""),
                    "server_schema_revision": snapshot.get("schema_revision", ""),
                    "last_successful_sync_at": now,
                    "last_full_refresh_at": now,
                    "last_change_cursor": snapshot.get("cursor", 0),
                    "server_revision": snapshot.get("server_revision", ""),
                    "data_revision": snapshot.get("data_status", {}).get("data_revision", ""),
                    "data_last_modified_at": snapshot.get("data_status", {}).get("data_last_modified_at", ""),
                    "last_import_at": snapshot.get("data_status", {}).get("last_import_at", ""),
                    "last_import_source": snapshot.get("data_status", {}).get("last_import_source", ""),
                },
            )
            connection.commit()

    def replace_with(self, temporary: Path) -> None:
        backup = self.path.with_suffix(self.path.suffix + ".previous")
        if backup.exists():
            backup.unlink()
        if self.path.exists():
            os.replace(self.path, backup)
        try:
            os.replace(temporary, self.path)
            self.validate()
        except Exception:
            if self.path.exists():
                self.path.unlink()
            if backup.exists():
                os.replace(backup, self.path)
            raise
        if backup.exists():
            backup.unlink()

    def validate(self, path: Path | None = None) -> dict[str, int]:
        target = path or self.path
        if not target.exists():
            raise CacheUnavailableError("The disposable API cache has not been built.")
        with closing(self._connect(target)) as connection:
            metadata = {row["key"]: row["value"] for row in connection.execute("SELECT key,value FROM cache_metadata")}
            if metadata.get("cache_schema_version") != CACHE_SCHEMA_VERSION:
                raise CacheUnavailableError("Cache schema version is incompatible.")
            counts = {
                row["entity_type"]: row["count"]
                for row in connection.execute(
                    "SELECT entity_type,COUNT(*) AS count FROM cached_entities GROUP BY entity_type"
                )
            }
            if not counts.get("eoats") or not counts.get("machines") or not counts.get("tools"):
                raise CacheUnavailableError("Replacement cache is missing required entity sets.")
            counts["eoat_history"] = int(connection.execute("SELECT COUNT(*) FROM cached_eoat_history").fetchone()[0])
            return counts

    def get(self, entity_type: str, identifier: str) -> dict[str, Any] | None:
        if not self.path.exists():
            return None
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT payload_json FROM cached_entities WHERE entity_type=? AND lower(identifier)=lower(?)",
                (entity_type, identifier),
            ).fetchone()
            return json.loads(row[0]) if row else None

    def list(self, entity_type: str) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        with closing(self._connect()) as connection:
            return [
                json.loads(row[0])
                for row in connection.execute(
                    "SELECT payload_json FROM cached_entities WHERE entity_type=? ORDER BY identifier", (entity_type,)
                )
            ]

    def get_eoat_history(self, identifier: str) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        with closing(self._connect()) as connection:
            return [
                json.loads(row[0])
                for row in connection.execute(
                    "SELECT payload_json FROM cached_eoat_history WHERE lower(eoat_identifier)=lower(?) "
                    "ORDER BY occurred_at DESC, event_id DESC",
                    (identifier,),
                )
            ]

    def linked_documents(self, entity_type: str, identifier: str, *, photos_only: bool = False) -> list[dict[str, Any]]:
        """Return only documents explicitly linked to the requested stable entity identifier."""
        if not self.path.exists():
            return []
        cached_type = "photos" if photos_only else "documents"
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT e.payload_json FROM cached_document_links l "
                "JOIN cached_entities e ON e.identifier=l.document_identifier AND e.entity_type=? "
                "WHERE lower(l.entity_type)=lower(?) AND lower(l.entity_identifier)=lower(?) "
                "ORDER BY e.identifier",
                (cached_type, entity_type, identifier),
            ).fetchall()
            return [json.loads(row[0]) for row in rows]

    def get_machine(self, number: str, *, plant_code: str | None = None) -> dict[str, Any] | None:
        matches = [
            value
            for value in self.list("machines")
            if str(value.get("machine_number")) == str(number)
            and (plant_code is None or str(value.get("plant_code")) == str(plant_code))
        ]
        if len(matches) > 1:
            raise CacheUnavailableError("Machine number is ambiguous in the offline cache; plant_code is required.")
        return matches[0] if matches else None

    def replace_eoat_history(self, identifier: str, events: list[dict[str, Any]]) -> None:
        self.initialize()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM cached_eoat_history WHERE lower(eoat_identifier)=lower(?)", (identifier,))
            for payload in events:
                event_id = str(payload.get("event_id") or "").strip()
                if not event_id:
                    raise CacheUnavailableError("History response contains an event without an event ID.")
                connection.execute(
                    "INSERT INTO cached_eoat_history(eoat_identifier,event_id,occurred_at,payload_json) VALUES(?,?,?,?)",
                    (identifier, event_id, payload.get("occurred_at"), json.dumps(payload, ensure_ascii=False)),
                )
            self._put_metadata(connection, {"last_history_sync_at": datetime.now(timezone.utc).isoformat()})
            connection.commit()

    def search(self, query: str, limit: int = 50) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        safe = " ".join(part for part in query.replace('"', " ").split() if part)
        if not safe:
            return []
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT entity_type,identifier FROM cached_entities "
                "WHERE entity_type IN ('eoats','machines','tools') AND lower(payload_json) LIKE ? "
                "ORDER BY entity_type,identifier LIMIT ?",
                (f"%{safe.casefold()}%", limit),
            ).fetchall()
        categories = {"eoats": "eoat", "machines": "machine", "tools": "tool"}
        return [
            {
                "category": categories.get(row["entity_type"], row["entity_type"]),
                "identifier": row["identifier"],
                "title": row["identifier"],
                "subtitle": "Offline cached result",
                "matched_field": "cache_search",
            }
            for row in rows
        ]

    def apply_change_cursor(self, changes: dict[str, Any]) -> None:
        self.initialize()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            for change in changes.get("changes", []):
                connection.execute(
                    "INSERT OR REPLACE INTO cached_changes(cursor,payload_json) VALUES(?,?)",
                    (change["cursor"], json.dumps(change)),
                )
            self._put_metadata(
                connection,
                {
                    "last_change_cursor": changes.get("next_cursor", 0),
                    "last_successful_sync_at": datetime.now(timezone.utc).isoformat(),
                },
            )
            connection.commit()

    def status(self) -> CacheStatus:
        metadata = self.metadata()
        counts = self.validate() if self.path.exists() else {}
        return CacheStatus(
            path=str(self.path),
            exists=self.path.exists(),
            schema_version=metadata.get("cache_schema_version", ""),
            api_version=metadata.get("api_version", ""),
            server_schema_revision=metadata.get("server_schema_revision", ""),
            last_successful_sync_at=metadata.get("last_successful_sync_at", ""),
            last_full_refresh_at=metadata.get("last_full_refresh_at", ""),
            last_change_cursor=int(metadata.get("last_change_cursor", 0)),
            server_revision=metadata.get("server_revision", ""),
            entity_counts=counts,
        )
