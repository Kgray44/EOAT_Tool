from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


RUNTIME_FOLDER_NAME = "EOAT_Atlas_Dev"
PRODUCTION_RUNTIME_FOLDER_NAME = "EOAT_Atlas"


@dataclass(frozen=True)
class AtlasRuntimePaths:
    runtime_root: Path
    config_dir: Path
    config_path: Path
    settings_path: Path
    settings_dir: Path
    data_dir: Path
    db_path: Path
    previous_db_path: Path
    cache_manifest_path: Path
    pending_updates_dir: Path
    events_dir: Path
    event_outbox_dir: Path
    event_written_dir: Path
    event_failed_dir: Path
    sync_dir: Path
    sync_attempts_dir: Path
    local_lock_diagnostics_dir: Path
    workbook_staging_dir: Path
    backups_dir: Path
    thumbnail_cache_dir: Path
    logs_dir: Path
    crash_reports_dir: Path
    temp_dir: Path
    install_identity_path: Path

    @property
    def local_cache_metadata_path(self) -> Path:
        return self.cache_manifest_path

    def directories(self) -> tuple[Path, ...]:
        return (
            self.runtime_root,
            self.config_dir,
            self.settings_dir,
            self.data_dir,
            self.pending_updates_dir,
            self.events_dir,
            self.event_outbox_dir,
            self.event_written_dir,
            self.event_failed_dir,
            self.sync_dir,
            self.sync_attempts_dir,
            self.local_lock_diagnostics_dir,
            self.workbook_staging_dir,
            self.backups_dir,
            self.thumbnail_cache_dir,
            self.logs_dir,
            self.crash_reports_dir,
            self.temp_dir,
        )


def get_runtime_paths(base_dir: str | Path | None = None) -> AtlasRuntimePaths:
    base = Path(base_dir) if base_dir else _default_local_appdata()
    root = base.expanduser() / _runtime_folder_name()
    return AtlasRuntimePaths(
        runtime_root=root,
        config_dir=root / "config",
        config_path=root / "config" / "global_config.json",
        settings_path=root / "settings.json",
        settings_dir=root / "config",
        data_dir=root / "data",
        db_path=root / "data" / "local_cache.db",
        previous_db_path=root / "data" / "local_cache.previous.db",
        cache_manifest_path=root / "data" / "cache_manifest.json",
        pending_updates_dir=root / "pending",
        events_dir=root / "events",
        event_outbox_dir=root / "events" / "outbox",
        event_written_dir=root / "events" / "written",
        event_failed_dir=root / "events" / "failed",
        sync_dir=root / "sync",
        sync_attempts_dir=root / "sync" / "sync_attempts",
        local_lock_diagnostics_dir=root / "sync" / "locks",
        workbook_staging_dir=root / "staging",
        backups_dir=root / "backups",
        thumbnail_cache_dir=root / "thumbnails",
        logs_dir=root / "logs",
        crash_reports_dir=root / "crash_reports",
        temp_dir=root / "temp",
        install_identity_path=root / "install_identity.json",
    )


def ensure_runtime_layout(paths: AtlasRuntimePaths | None = None) -> AtlasRuntimePaths:
    runtime = paths or get_runtime_paths()
    for directory in runtime.directories():
        directory.mkdir(parents=True, exist_ok=True)
    _migrate_legacy_runtime_layout(runtime)
    if not runtime.settings_path.exists():
        atomic_write_json(
            runtime.settings_path,
            {
                "created_at": _now_iso(),
                "runtime_root": str(runtime.runtime_root),
                "environment": "development",
            },
        )
    return runtime


def _migrate_legacy_runtime_layout(runtime: AtlasRuntimePaths) -> None:
    legacy_targets = (
        (runtime.runtime_root / "config.json", runtime.config_path),
        (runtime.runtime_root / "pending_local_updates", runtime.pending_updates_dir),
        (runtime.runtime_root / "event_outbox", runtime.event_outbox_dir),
        (runtime.runtime_root / "workbook_staging", runtime.workbook_staging_dir),
        (runtime.runtime_root / "cache" / "thumbnails", runtime.thumbnail_cache_dir),
    )
    for source, target in legacy_targets:
        if not source.exists() or source == target:
            continue
        if source.is_file():
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
            continue
        for path in source.glob("*"):
            destination = target / path.name
            if destination.exists():
                continue
            if path.is_file():
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, destination)


def atomic_write_json(path: str | Path, payload: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
        Path(tmp_name).replace(target)
    except Exception:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def read_json(path: str | Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    target = Path(path)
    if not target.exists():
        return dict(default or {})
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return dict(default or {})


def _default_local_appdata() -> Path:
    override = os.environ.get("EOAT_ATLAS_LOCALAPPDATA")
    if override:
        return Path(override)
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        return Path(local_appdata)
    return Path.home() / "AppData" / "Local"


def _runtime_folder_name() -> str:
    override = os.environ.get("EOAT_ATLAS_RUNTIME_FOLDER_NAME")
    if override:
        return override
    if bool(getattr(sys, "frozen", False)) and os.environ.get("EOAT_ATLAS_DEV_RUNTIME") != "1":
        return PRODUCTION_RUNTIME_FOLDER_NAME
    return RUNTIME_FOLDER_NAME


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")
