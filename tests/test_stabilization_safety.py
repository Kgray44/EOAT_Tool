from __future__ import annotations

from pathlib import Path

import pytest

from core.data_gateway.cache_repository import CACHE_SCHEMA_VERSION, CacheRepository
from server.eoat_api.compatibility import classify_status
from server.eoat_api.database.session import (
    create_database_engine,
    create_session_factory,
    dispose_database_engines,
)
from server.eoat_api.write_services import COMPATIBILITY_WRITABLE_FIELDS


@pytest.mark.parametrize("code", ["compatible", "verified_compatible", "approved"])
def test_only_explicit_compatible_statuses_pass(code: str) -> None:
    assert classify_status(code) == "COMPATIBLE"


@pytest.mark.parametrize("code", [None, "", "unknown", "unexpected", "pending"])
def test_missing_or_unrecognized_status_fails_closed(code: str | None) -> None:
    assert classify_status(code) == "UNKNOWN"


@pytest.mark.parametrize("code", ["needs_review", "review_required"])
def test_review_status_is_not_compatible(code: str) -> None:
    assert classify_status(code) == "NEEDS_REVIEW"


def test_compatibility_allowlists_exclude_system_fields() -> None:
    blocked = {
        "id", "eoat_id", "tool_id", "machine_id", "is_active", "row_version", "created_at", "updated_at",
        "created_by_user_id", "updated_by_user_id", "verified_by_user_id", "archived_at", "source_import_batch_id",
    }
    assert set(COMPATIBILITY_WRITABLE_FIELDS) == {"eoat-machine", "eoat-tool", "tool-machine"}
    assert all(not (blocked & fields) for fields in COMPATIBILITY_WRITABLE_FIELDS.values())


def test_cache_links_documents_and_photos_to_exact_eoat(tmp_path: Path) -> None:
    cache = CacheRepository(tmp_path / "cache.db")
    base = {
        "api_version": "1.3.0",
        "schema_revision": "test",
        "server_revision": "test",
        "cursor": 0,
        "lookups": {},
        "eoats": [{"business_identifier": "DEMO-EOAT-0001"}, {"business_identifier": "DEMO-EOAT-0002"}],
        "machines": [{"machine_number": "DEMO-MACHINE-040"}],
        "tools": [{"business_identifier": "DEMO-TOOL-1001"}],
        "documents": [
            {"document_uuid": "doc-a", "title": "A", "related_entities": [{"relationship_type": "eoat", "identifier": "DEMO-EOAT-0001"}]},
            {"document_uuid": "doc-b", "title": "B", "related_entities": [{"relationship_type": "eoat", "identifier": "DEMO-EOAT-0002"}]},
        ],
        "photos": [
            {"document_uuid": "photo-a", "title": "Photo A", "is_profile_photo": True, "related_entities": [{"relationship_type": "eoat", "identifier": "DEMO-EOAT-0001"}]},
            {"document_uuid": "photo-b", "title": "Photo B", "related_entities": [{"relationship_type": "eoat", "identifier": "DEMO-EOAT-0002"}]},
        ],
    }
    cache.build_snapshot(base, cache.path)
    assert CACHE_SCHEMA_VERSION == "4"
    assert [row["document_uuid"] for row in cache.linked_documents("eoat", "DEMO-EOAT-0001")] == ["doc-a"]
    assert [row["document_uuid"] for row in cache.linked_documents("eoat", "DEMO-EOAT-0001", photos_only=True)] == ["photo-a"]


def test_stale_cache_schema_is_rejected(tmp_path: Path) -> None:
    cache = CacheRepository(tmp_path / "cache.db")
    cache.initialize()
    import sqlite3

    with sqlite3.connect(cache.path) as connection:
        connection.execute("UPDATE cache_metadata SET value='3' WHERE key='cache_schema_version'")
    with pytest.raises(Exception, match="schema version"):
        cache.validate()


def test_runtime_engine_and_factory_are_process_reused() -> None:
    dispose_database_engines()
    first_engine = create_database_engine(migration=False)
    second_engine = create_database_engine(migration=False)
    first_factory = create_session_factory(migration=False)
    second_factory = create_session_factory(migration=False)
    assert first_engine is second_engine
    assert first_factory is second_factory
    assert first_factory.kw["bind"] is first_engine
    dispose_database_engines()
    assert create_database_engine(migration=False) is not first_engine
    dispose_database_engines()
