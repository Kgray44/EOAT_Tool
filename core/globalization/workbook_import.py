from __future__ import annotations

import hashlib
import os
import shutil
import uuid
from collections.abc import Callable
from dataclasses import fields, replace
from datetime import datetime
from pathlib import Path
from typing import Any

from core.atlas_models import AtlasDataBundle

from .config import load_or_create_global_config
from .events import EventOutbox
from .pending_updates import pending_updates_for_entity, reindex_pending_updates
from .runtime_paths import AtlasRuntimePaths, atomic_write_json, ensure_runtime_layout, get_runtime_paths
from .sqlite_store import cache_metadata, connect_cache_db, read_bundle, write_bundle

LegacyLoader = Callable[..., AtlasDataBundle]
WORKBOOK_KEYS = {"eoat_master_tracker", "press_capacity_workbook", "robot_workbook"}


def should_use_sqlite_cache(source_paths: dict[str, str] | None) -> bool:
    if not source_paths:
        return False
    return bool(str(source_paths.get("eoat_master_tracker") or "").strip())


def load_atlas_data_from_sqlite_cache(
    project_root: str | Path,
    *,
    force_refresh: bool = False,
    exclude_unaudited_tools: bool = True,
    source_paths: dict[str, str] | None = None,
    legacy_loader: LegacyLoader,
) -> AtlasDataBundle:
    runtime = ensure_runtime_layout(get_runtime_paths())
    config = load_or_create_global_config(runtime)
    configured_source_paths = dict(config.source_paths())
    configured_source_paths.update({key: value for key, value in (source_paths or {}).items() if str(value or "").strip()})

    if not force_refresh and runtime.db_path.exists():
        cached = _read_cached_bundle(runtime)
        if cached is not None:
            pending_count = _reindex_pending_for_active_cache(runtime)
            cached = _bundle_with_pending_overlays(cached, runtime)
            cached.metrics.update(
                {
                    "sqlite_cache_hit": True,
                    "sqlite_cache_refreshed": False,
                    "local_refresh": True,
                    "deep_refresh": False,
                    "pending_update_count": pending_count,
                    "offline_cache_used": False,
                }
            )
            return cached

    unavailable = _required_sources_unavailable(configured_source_paths)
    if unavailable and runtime.db_path.exists():
        cached = _read_cached_bundle(runtime)
        if cached is not None:
            pending_count = _reindex_pending_for_active_cache(runtime)
            cached = _bundle_with_pending_overlays(cached, runtime)
            cached.metrics.update(
                {
                    "sqlite_cache_hit": True,
                    "sqlite_cache_refreshed": False,
                    "local_refresh": True,
                    "deep_refresh": False,
                    "pending_update_count": pending_count,
                    "offline_cache_used": True,
                    "offline_missing_sources": unavailable,
                }
            )
            return cached

    return _refresh_cache(
        runtime,
        project_root=project_root,
        source_paths=configured_source_paths,
        legacy_loader=legacy_loader,
        exclude_unaudited_tools=exclude_unaudited_tools,
    )


def refresh_from_local_sqlite_cache(runtime: AtlasRuntimePaths | None = None) -> AtlasDataBundle:
    paths = ensure_runtime_layout(runtime or get_runtime_paths())
    if not paths.db_path.exists():
        raise FileNotFoundError(f"No local EOAT Atlas SQLite cache exists: {paths.db_path}")
    bundle = _read_cached_bundle(paths)
    if bundle is None:
        raise ValueError(f"Local EOAT Atlas SQLite cache is empty: {paths.db_path}")
    pending_count = _reindex_pending_for_active_cache(paths)
    bundle = _bundle_with_pending_overlays(bundle, paths)
    bundle.metrics.update(
        {
            "sqlite_cache_hit": True,
            "sqlite_cache_refreshed": False,
            "local_refresh": True,
            "deep_refresh": False,
            "pending_update_count": pending_count,
            "sqlite_cache_path": str(paths.db_path),
        }
    )
    return bundle


def deep_refresh_sqlite_cache(
    project_root: str | Path,
    *,
    exclude_unaudited_tools: bool = True,
    source_paths: dict[str, str] | None = None,
    legacy_loader: LegacyLoader,
    runtime: AtlasRuntimePaths | None = None,
) -> AtlasDataBundle:
    paths = ensure_runtime_layout(runtime or get_runtime_paths())
    config = load_or_create_global_config(paths)
    configured_source_paths = dict(config.source_paths())
    configured_source_paths.update({key: value for key, value in (source_paths or {}).items() if str(value or "").strip()})
    return _refresh_cache(
        paths,
        project_root=project_root,
        source_paths=configured_source_paths,
        legacy_loader=legacy_loader,
        exclude_unaudited_tools=exclude_unaudited_tools,
    )


def cache_health_summary(runtime: AtlasRuntimePaths | None = None) -> dict[str, Any]:
    paths = ensure_runtime_layout(runtime or get_runtime_paths())
    config = load_or_create_global_config(paths)
    db_exists = paths.db_path.exists()
    metadata: dict[str, Any] = {}
    conflict_count = 0
    if db_exists:
        try:
            with connect_cache_db(paths.db_path) as conn:
                metadata = cache_metadata(conn)
                conflict_count = int(conn.execute("SELECT COUNT(*) FROM conflicts WHERE status = 'open'").fetchone()[0])
        except Exception as exc:
            metadata = {"error": str(exc)}
    cache_age_seconds = None
    try:
        cache_age_seconds = int(datetime.now().timestamp() - paths.db_path.stat().st_mtime) if db_exists else None
    except OSError:
        cache_age_seconds = None
    pending_count = len(list(paths.pending_updates_dir.glob("*.json"))) if paths.pending_updates_dir.exists() else 0
    event_count = len(list(paths.event_outbox_dir.glob("*.json"))) if paths.event_outbox_dir.exists() else 0
    source_paths = config.source_paths()
    master = Path(source_paths.get("eoat_master_tracker") or "")
    master_signature = _file_signature(master) if str(master) else {}
    source_files = metadata.get("source_files", {}) if isinstance(metadata, dict) else {}
    import_runs = metadata.get("import_runs", []) if isinstance(metadata, dict) else []
    latest_import = import_runs[0] if import_runs else {}
    return {
        "environment": config.environment,
        "app_name": config.product_name,
        "app_version": config.app_version,
        "release_id": config.release_id,
        "build_id": config.build_id,
        "install_id": config.install_id,
        "app_instance_id": config.app_instance_id,
        "write_mode": config.write_mode,
        "network_root": config.network_root,
        "network_available": Path(config.network_root).exists() if config.network_root else False,
        "master_workbook_path": str(master),
        "source_workbook_fingerprint": master_signature,
        "runtime_root": str(paths.runtime_root),
        "cache_path": str(paths.db_path),
        "db_path": str(paths.db_path),
        "db_exists": db_exists,
        "cache_age_seconds": cache_age_seconds,
        "last_successful_refresh": latest_import.get("completed_at") or metadata.get("meta", {}).get("last_refresh", ""),
        "cached_counts": {
            "eoats": latest_import.get("eoat_count", 0),
            "tools": latest_import.get("tool_count", 0),
            "machines": latest_import.get("machine_count", 0),
        },
        "source_files": source_files,
        "pending_update_count": pending_count,
        "event_outbox_count": event_count,
        "conflict_count": conflict_count,
        "metadata": metadata,
    }


def _refresh_cache(
    runtime: AtlasRuntimePaths,
    *,
    project_root: str | Path,
    source_paths: dict[str, str],
    legacy_loader: LegacyLoader,
    exclude_unaudited_tools: bool,
) -> AtlasDataBundle:
    import_id = uuid.uuid4().hex
    started_at = datetime.now().isoformat(timespec="seconds")
    config = load_or_create_global_config(runtime)
    try:
        staged_paths, source_metadata = _stage_source_files(runtime, source_paths, import_id=import_id, staged_at=started_at)
        bundle = legacy_loader(
            Path(project_root),
            exclude_unaudited_tools=exclude_unaudited_tools,
            source_paths=staged_paths,
        )
        bundle = _restore_source_status_paths(bundle, source_paths)
        _validate_bundle(bundle)
        db_new = runtime.db_path.with_suffix(".new.db")
        for path in (db_new,):
            path.unlink(missing_ok=True)
        with connect_cache_db(db_new) as conn:
            write_bundle(conn, bundle, import_id=import_id, source_metadata=source_metadata, started_at=started_at)
            pending_count = reindex_pending_updates(conn, runtime.pending_updates_dir)
        if runtime.db_path.exists():
            runtime.previous_db_path.unlink(missing_ok=True)
            runtime.db_path.replace(runtime.previous_db_path)
        db_new.replace(runtime.db_path)
        _write_manifest(runtime, source_metadata)
        EventOutbox(runtime, config).create_event(
            event_type="deep_refresh_succeeded",
            action="deep_refresh",
            payload={
                "workbook_path": source_paths.get("eoat_master_tracker", ""),
                "workbook_fingerprint_before": source_metadata.get("eoat_master_tracker", {}),
                "write_result": {"status": "cache_rebuilt"},
                "validation_result": {"status": "valid"},
                "conflict_result": {"status": "not_applicable"},
            },
        )
        bundle = _bundle_with_pending_overlays(bundle, runtime)
        bundle.metrics.update(
            {
                "sqlite_cache_hit": False,
                "sqlite_cache_refreshed": True,
                "local_refresh": False,
                "deep_refresh": True,
                "pending_update_count": pending_count,
                "offline_cache_used": False,
                "sqlite_cache_path": str(runtime.db_path),
                "workbooks_staged": {
                    key: metadata["copied_to"] for key, metadata in source_metadata.items() if metadata.get("copied_to")
                },
            }
        )
        return bundle
    except Exception as exc:
        EventOutbox(runtime, config).create_event(
            event_type="deep_refresh_failed",
            action="deep_refresh",
            payload={
                "workbook_path": source_paths.get("eoat_master_tracker", ""),
                "write_result": {"status": "failed"},
                "validation_result": {"status": "failed"},
                "conflict_result": {"status": "not_applicable"},
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            },
        )
        raise


def _stage_source_files(
    runtime: AtlasRuntimePaths,
    source_paths: dict[str, str],
    *,
    import_id: str,
    staged_at: str,
) -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
    import_dir = runtime.workbook_staging_dir / import_id
    import_dir.mkdir(parents=True, exist_ok=True)
    staged_paths = dict(source_paths)
    metadata: dict[str, dict[str, Any]] = {}
    for key, value in source_paths.items():
        path = Path(value)
        copied_to = ""
        exists = path.exists()
        stat = path.stat() if exists else None
        if key in WORKBOOK_KEYS and exists and path.is_file():
            target = import_dir / path.name
            shutil.copy2(path, target)
            staged_paths[key] = str(target)
            copied_to = str(target)
        metadata[key] = {
            "source_path": str(path),
            "copied_to": copied_to,
            "exists_at_import": exists,
            "size": int(stat.st_size) if stat else 0,
            "mtime_ns": int(stat.st_mtime_ns) if stat else 0,
            "sha256": _sha256_file(path) if exists and path.is_file() else "",
            "staged_at": staged_at,
        }
    return staged_paths, metadata


def _source_metadata_matches(runtime: AtlasRuntimePaths, source_paths: dict[str, str]) -> bool:
    try:
        with connect_cache_db(runtime.db_path) as conn:
            metadata = cache_metadata(conn).get("source_files", {})
    except Exception:
        return False
    for key, value in source_paths.items():
        current = _file_signature(Path(value))
        cached = metadata.get(key)
        if not cached:
            return False
        if current["exists_at_import"] != bool(cached.get("exists_at_import")):
            return False
        if current["size"] != int(cached.get("size") or 0):
            return False
        if current["mtime_ns"] != int(cached.get("mtime_ns") or 0):
            return False
    return True


def _file_signature(path: Path) -> dict[str, Any]:
    exists = path.exists()
    if not exists:
        return {"exists_at_import": False, "size": 0, "mtime_ns": 0}
    stat = path.stat()
    return {"exists_at_import": True, "size": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns)}


def _required_sources_unavailable(source_paths: dict[str, str]) -> list[str]:
    missing: list[str] = []
    for key in ("eoat_master_tracker", "press_capacity_workbook"):
        value = source_paths.get(key)
        if value and not Path(value).exists():
            missing.append(key)
    return missing


def _read_cached_bundle(runtime: AtlasRuntimePaths) -> AtlasDataBundle | None:
    with connect_cache_db(runtime.db_path) as conn:
        return read_bundle(conn)


def _reindex_pending_for_active_cache(runtime: AtlasRuntimePaths) -> int:
    with connect_cache_db(runtime.db_path) as conn:
        return reindex_pending_updates(conn, runtime.pending_updates_dir)


def _bundle_with_pending_overlays(bundle: AtlasDataBundle, runtime: AtlasRuntimePaths) -> AtlasDataBundle:
    """Return UI-facing effective records while leaving the SQLite cache as imported source data."""
    return replace(
        bundle,
        eoats=tuple(_record_with_pending_overlay(record, "eoat", record.eoat_id, runtime) for record in bundle.eoats),
        tools=tuple(_record_with_pending_overlay(record, "tool", record.tool, runtime) for record in bundle.tools),
        machines=tuple(_record_with_pending_overlay(record, "machine", record.machine, runtime) for record in bundle.machines),
    )


def _record_with_pending_overlay(record: Any, entity_type: str, entity_id: str, runtime: AtlasRuntimePaths) -> Any:
    updates = pending_updates_for_entity(runtime.pending_updates_dir, entity_type=entity_type, entity_id=entity_id)
    if not updates:
        return record
    field_lookup = {_normalized_field_name(field.name): field.name for field in fields(record)}
    values: dict[str, Any] = {}
    for update in updates:
        if str(update.get("validation_status") or "valid").casefold() not in {"valid", "not_run"}:
            continue
        if str(update.get("sync_status") or update.get("workbook_sync_status") or "not_started").casefold() in {"succeeded", "cleared"}:
            continue
        field_name = field_lookup.get(_normalized_field_name(str(update.get("field_name") or update.get("field") or "")))
        if field_name:
            values[field_name] = update.get("proposed_value")
    return replace(record, **values) if values else record


def _normalized_field_name(value: str) -> str:
    return "".join(char for char in str(value or "").casefold() if char.isalnum())


def _validate_bundle(bundle: AtlasDataBundle) -> None:
    if not bundle.eoats:
        raise ValueError("SQLite cache refresh produced no EOAT records.")
    if bundle.metrics is None:
        raise ValueError("SQLite cache refresh produced no metrics.")


def _restore_source_status_paths(bundle: AtlasDataBundle, source_paths: dict[str, str]) -> AtlasDataBundle:
    source_labels = {
        "EOAT Master Tracker": "eoat_master_tracker",
        "Press Capacity": "press_capacity_workbook",
        "Robot Info": "robot_workbook",
        "EOAT Photos": "photos_root",
        "Standards": "reference_docs_folder",
    }
    statuses = []
    for status in bundle.source_statuses:
        key = source_labels.get(status.label)
        if key and str(source_paths.get(key) or "").strip():
            statuses.append(replace(status, path=str(source_paths[key])))
        else:
            statuses.append(status)
    return replace(bundle, source_statuses=tuple(statuses))


def _write_manifest(runtime: AtlasRuntimePaths, source_metadata: dict[str, dict[str, Any]]) -> None:
    payload = {
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "pid": os.getpid(),
        "db_path": str(runtime.db_path),
        "source_files": source_metadata,
    }
    atomic_write_json(runtime.cache_manifest_path, payload)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
