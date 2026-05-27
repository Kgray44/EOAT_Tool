from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

LATEST_SCHEMA_VERSION = 1


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def applied_versions(conn: sqlite3.Connection) -> set[int]:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
        """
    )
    return {int(row[0]) for row in conn.execute("SELECT version FROM schema_migrations")}


def apply_migrations(conn: sqlite3.Connection) -> None:
    versions = applied_versions(conn)
    if 1 not in versions:
        _create_v1_schema(conn)
        conn.execute("INSERT INTO schema_migrations(version, applied_at) VALUES(?, ?)", (1, utc_now()))
    conn.commit()


def _create_v1_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS notes (
            id TEXT PRIMARY KEY,
            subject TEXT NOT NULL,
            body_markdown TEXT NOT NULL DEFAULT '',
            importance TEXT NOT NULL DEFAULT 'Neutral',
            status TEXT,
            collection TEXT,
            note_type TEXT,
            follow_up_date TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            archived_at TEXT
        );

        CREATE TABLE IF NOT EXISTS tags (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            color_key TEXT NOT NULL,
            description TEXT,
            is_default INTEGER NOT NULL DEFAULT 0,
            is_archived INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS annotation_targets (
            id TEXT PRIMARY KEY,
            target_type TEXT NOT NULL,
            target_label TEXT,
            audit_id TEXT,
            machine_id TEXT,
            field_key TEXT,
            field_label TEXT,
            sheet_name TEXT,
            header_name TEXT,
            workbook_path TEXT,
            cached_cell_ref TEXT,
            object_ref TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS tag_assignments (
            id TEXT PRIMARY KEY,
            tag_id TEXT NOT NULL,
            target_id TEXT NOT NULL,
            comment TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            archived_at TEXT,
            FOREIGN KEY(tag_id) REFERENCES tags(id),
            FOREIGN KEY(target_id) REFERENCES annotation_targets(id)
        );

        CREATE TABLE IF NOT EXISTS note_targets (
            id TEXT PRIMARY KEY,
            note_id TEXT NOT NULL,
            target_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(note_id) REFERENCES notes(id),
            FOREIGN KEY(target_id) REFERENCES annotation_targets(id)
        );

        CREATE TABLE IF NOT EXISTS note_tags (
            id TEXT PRIMARY KEY,
            note_id TEXT NOT NULL,
            tag_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(note_id) REFERENCES notes(id),
            FOREIGN KEY(tag_id) REFERENCES tags(id)
        );

        CREATE TABLE IF NOT EXISTS attachments (
            id TEXT PRIMARY KEY,
            note_id TEXT,
            target_id TEXT,
            file_path TEXT NOT NULL,
            display_name TEXT,
            description TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(note_id) REFERENCES notes(id),
            FOREIGN KEY(target_id) REFERENCES annotation_targets(id)
        );

        CREATE INDEX IF NOT EXISTS idx_notes_importance ON notes(importance);
        CREATE INDEX IF NOT EXISTS idx_notes_status ON notes(status);
        CREATE INDEX IF NOT EXISTS idx_notes_collection ON notes(collection);
        CREATE INDEX IF NOT EXISTS idx_notes_type ON notes(note_type);
        CREATE INDEX IF NOT EXISTS idx_targets_type ON annotation_targets(target_type);
        CREATE INDEX IF NOT EXISTS idx_targets_audit ON annotation_targets(audit_id);
        CREATE INDEX IF NOT EXISTS idx_targets_machine ON annotation_targets(machine_id);
        CREATE INDEX IF NOT EXISTS idx_targets_field ON annotation_targets(field_key);
        CREATE INDEX IF NOT EXISTS idx_tag_assignments_tag ON tag_assignments(tag_id);
        CREATE INDEX IF NOT EXISTS idx_tag_assignments_target ON tag_assignments(target_id);
        CREATE INDEX IF NOT EXISTS idx_note_targets_note ON note_targets(note_id);
        CREATE INDEX IF NOT EXISTS idx_note_targets_target ON note_targets(target_id);
        CREATE INDEX IF NOT EXISTS idx_note_tags_note ON note_tags(note_id);
        CREATE INDEX IF NOT EXISTS idx_note_tags_tag ON note_tags(tag_id);
        """
    )
