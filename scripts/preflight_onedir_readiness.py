from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


FORBIDDEN_RELEASE_STRINGS = (
    "EOAT_" + "Command_" + "Center",
    "eoat_" + "command_" + "center_entry",
    "run_" + "dashboard",
    "app.dashboard" + "_ui",
    "app.atlas.atlas" + "_window",
)


class Preflight:
    def __init__(self) -> None:
        self.failures: list[str] = []

    def pass_(self, message: str) -> None:
        print(f"PASS {message}")

    def fail(self, message: str) -> None:
        print(f"FAIL {message}")
        self.failures.append(message)

    def check(self, message: str, predicate: Callable[[], bool]) -> None:
        try:
            ok = bool(predicate())
        except Exception as exc:
            self.fail(f"{message}: {type(exc).__name__}: {exc}")
            return
        if ok:
            self.pass_(message)
        else:
            self.fail(message)


def main() -> int:
    preflight = Preflight()
    _check_static_files(preflight)
    with tempfile.TemporaryDirectory(prefix="eoat_atlas_preflight_") as temp_root:
        _check_runtime_gates(preflight, Path(temp_root))
    return 1 if preflight.failures else 0


def _check_static_files(preflight: Preflight) -> None:
    entry = ROOT / "run_atlas.py"
    packaging_entry = ROOT / "packaging" / "eoat_atlas_entry.py"
    spec = ROOT / "EOAT_Atlas.spec"
    metadata = ROOT / "release_metadata.json"
    smoke = ROOT / "scripts" / "smoke_test_package.py"

    preflight.check("active entry point exists", lambda: entry.exists())
    preflight.check("packaging entry point exists", lambda: packaging_entry.exists())
    preflight.check("spec file exists", lambda: spec.exists())
    preflight.check("release metadata file exists", lambda: metadata.exists())
    preflight.check("package smoke script exists", lambda: smoke.exists())

    from core.globalization.app_metadata import load_app_metadata

    loaded = load_app_metadata(ROOT)
    preflight.check("release metadata loads", lambda: loaded.app_name == "EOAT Atlas" and bool(loaded.release_id))
    preflight.check("release metadata has schema versions", lambda: loaded.cache_schema_version >= 1 and loaded.event_schema_version >= 1 and loaded.config_schema_version >= 1)

    spec_text = spec.read_text(encoding="utf-8")
    preflight.check("spec references minimalist packaging entry", lambda: '["packaging/eoat_atlas_entry.py"]' in spec_text)
    preflight.check("spec includes release_metadata.json", lambda: "release_metadata.json" in spec_text)
    preflight.check("spec output name is EOAT Atlas", lambda: 'name="EOAT Atlas"' in spec_text)
    preflight.check("spec does not include runtime cache/settings artifacts", lambda: all(token not in spec_text for token in ("local_cache.db", "install_identity.json", "events/outbox", "settings.json")))
    preflight.check("spec excludes old app entry targets", lambda: all(token not in spec_text for token in FORBIDDEN_RELEASE_STRINGS))

    active_paths = [
        ROOT / "run_atlas.py",
        ROOT / "packaging" / "eoat_atlas_entry.py",
        ROOT / "EOAT_Atlas.spec",
        ROOT / "app" / "atlas",
        ROOT / "core" / "globalization",
    ]
    offenders = _active_scope_offenders(active_paths)
    preflight.check("active release scope excludes old app targets", lambda: not offenders)
    if offenders:
        for offender in offenders:
            print(f"  offender: {offender}")


def _check_runtime_gates(preflight: Preflight, temp_root: Path) -> None:
    previous_env = {key: os.environ.get(key) for key in ("EOAT_ATLAS_LOCALAPPDATA", "EOAT_ATLAS_USER_DATA_DIR", "EOAT_ATLAS_RUNTIME_FOLDER_NAME")}
    os.environ["EOAT_ATLAS_LOCALAPPDATA"] = str(temp_root / "LocalAppData")
    os.environ["EOAT_ATLAS_USER_DATA_DIR"] = str(temp_root / "UserData")
    os.environ.pop("EOAT_ATLAS_RUNTIME_FOLDER_NAME", None)
    try:
        from core.atlas_models import AtlasDataBundle
        from core.globalization.config import load_or_create_global_config
        from core.globalization.events import EventOutbox, validate_event_payload
        from core.globalization.install_identity import load_or_create_install_identity
        from core.globalization.pending_updates import PendingUpdateStore
        from core.globalization.runtime_paths import ensure_runtime_layout, get_runtime_paths
        from core.globalization.sqlite_store import connect_cache_db, write_bundle
        from core.globalization.workbook_import import deep_refresh_sqlite_cache, refresh_from_local_sqlite_cache
        from core.globalization.write_foundation import SyncStatusService

        runtime = ensure_runtime_layout(get_runtime_paths())
        config = load_or_create_global_config(runtime)
        identity = load_or_create_install_identity(runtime)

        preflight.check("runtime root is under temp LocalAppData", lambda: temp_root in runtime.runtime_root.parents)
        preflight.check("runtime folders are created", lambda: all(path.exists() for path in runtime.directories()))
        preflight.check("install identity is created under runtime", lambda: runtime.install_identity_path.exists() and runtime.runtime_root in runtime.install_identity_path.parents)
        preflight.check("install identity persists", lambda: load_or_create_install_identity(runtime).install_id == identity.install_id)
        preflight.check("settings file is under runtime", lambda: runtime.settings_path.exists() and runtime.runtime_root in runtime.settings_path.parents)

        with connect_cache_db(runtime.db_path) as conn:
            write_bundle(
                conn,
                AtlasDataBundle(project_root=str(ROOT), loaded_at=datetime.now().isoformat(timespec="seconds")),
                import_id="preflight",
                source_metadata={},
                started_at=datetime.now().isoformat(timespec="seconds"),
            )
        refreshed = refresh_from_local_sqlite_cache(runtime)
        preflight.check("SQLite cache initializes under runtime", lambda: runtime.db_path.exists() and runtime.runtime_root in runtime.db_path.parents)
        preflight.check("local Refresh runs without workbook access", lambda: refreshed.metrics.get("local_refresh") is True and refreshed.metrics.get("deep_refresh") is False)
        preflight.check("Deep Refresh entry point is available", lambda: callable(deep_refresh_sqlite_cache))

        store = PendingUpdateStore(runtime, config)
        update = store.create_update(
            entity_type="eoat",
            entity_id="PREFLIGHT-EOAT",
            field_name="status",
            expected_original_value="Old",
            proposed_value="Ready",
            source_view="preflight",
            source_action="preflight_pending_update",
        )
        preflight.check("pending update writes under runtime", lambda: (runtime.pending_updates_dir / f"{update['pending_update_id']}.json").exists())
        preflight.check("pending update includes install identity", lambda: update.get("install_id") == config.install_id and bool(update.get("app_instance_id")))

        event = EventOutbox(runtime, config).create_event(
            event_type="preflight_event",
            action="preflight",
            entity_type="eoat",
            entity_id="PREFLIGHT-EOAT",
            payload={
                "pending_update_ids": [update["pending_update_id"]],
                "field_changes": [{"field_name": "status", "expected_original_value": "Old", "proposed_value": "Ready"}],
                "validation_result": {"status": "valid"},
                "conflict_result": {"status": "none"},
                "write_result": {"status": "not_written"},
                "source_view": "preflight",
                "source_action": "preflight",
            },
        )
        event_paths = list(runtime.event_outbox_dir.glob(f"*_{event['event_id']}.json"))
        validate_event_payload(event)
        preflight.check("event JSON writes under runtime", lambda: len(event_paths) == 1 and runtime.runtime_root in event_paths[0].parents)
        preflight.check("event JSON includes identity/version", lambda: event.get("install_id") == config.install_id and event.get("release_id") == config.release_id)
        preflight.check("production writes are disabled by default", lambda: SyncStatusService(config).status()["writes_enabled"] is False and config.write_mode == "disabled")
        preflight.check("source tree is not used for runtime writes", lambda: not _source_runtime_artifacts_exist())
    finally:
        for key, value in previous_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _active_scope_offenders(paths: list[Path]) -> list[str]:
    offenders: list[str] = []
    for path in paths:
        files = path.rglob("*.py") if path.is_dir() else (path,)
        for file_path in files:
            if not file_path.exists() or file_path.suffix not in {".py", ".spec"}:
                continue
            text = file_path.read_text(encoding="utf-8")
            for token in FORBIDDEN_RELEASE_STRINGS:
                if token in text:
                    offenders.append(f"{file_path.relative_to(ROOT)}: {token}")
    return offenders


def _source_runtime_artifacts_exist() -> bool:
    candidates = [
        ROOT / "install_identity.json",
        ROOT / "settings.json",
        ROOT / "data" / "local_cache.db",
        ROOT / "data" / "cache_manifest.json",
        ROOT / "pending",
        ROOT / "events" / "outbox",
        ROOT / "logs",
        ROOT / "staging",
        ROOT / "backups",
    ]
    return any(path.exists() for path in candidates)


if __name__ == "__main__":
    raise SystemExit(main())
