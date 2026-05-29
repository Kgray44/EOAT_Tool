from __future__ import annotations

import sqlite3
from pathlib import Path

from core.paths import resolve_project_paths
from core.safe_files import ensure_directory

from .migrations import LATEST_SCHEMA_VERSION, apply_migrations
from .tag_colors import DEFAULT_TAG_DEFINITIONS


def annotation_database_path(project_root: str | Path) -> Path:
    return resolve_project_paths(project_root).annotations_database


def connect_annotation_database(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(Path(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def initialize_annotation_database(project_root: str | Path, db_path: str | Path | None = None) -> Path:
    path = Path(db_path) if db_path else annotation_database_path(project_root)
    ensure_directory(path.parent)
    conn = connect_annotation_database(path)
    try:
        apply_migrations(conn)
        seed_default_tags(conn)
        conn.commit()
    finally:
        conn.close()
    return path


def current_schema_version(conn: sqlite3.Connection) -> int:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
        """
    )
    row = conn.execute("SELECT MAX(version) AS version FROM schema_migrations").fetchone()
    return int(row["version"] or 0)


def seed_default_tags(conn: sqlite3.Connection) -> int:
    from .migrations import utc_now

    inserted = 0
    now = utc_now()
    for definition in DEFAULT_TAG_DEFINITIONS:
        name = str(definition["name"])
        existing = conn.execute(
            "SELECT id FROM tags WHERE lower(name) = lower(?) AND is_default = 1",
            (name,),
        ).fetchone()
        if existing:
            continue
        tag_id = f"default_{name.casefold().replace(' ', '_').replace('/', '_')}"
        conn.execute(
            """
            INSERT OR IGNORE INTO tags(id, name, color_key, description, is_default, is_archived, created_at, updated_at)
            VALUES(?, ?, ?, ?, 1, 0, ?, ?)
            """,
            (tag_id, name, str(definition["color_key"]), str(definition.get("description") or ""), now, now),
        )
        inserted += conn.total_changes > 0
    return inserted


__all__ = [
    "LATEST_SCHEMA_VERSION",
    "annotation_database_path",
    "connect_annotation_database",
    "current_schema_version",
    "initialize_annotation_database",
    "seed_default_tags",
]
