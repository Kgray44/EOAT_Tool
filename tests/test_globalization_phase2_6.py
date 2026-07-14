from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from openpyxl import Workbook

from core import resources
from core.atlas_models import AtlasDataBundle
from core.globalization import app_metadata
from core.globalization.config import load_or_create_global_config
from core.globalization.events import EventOutbox
from core.globalization.install_identity import load_or_create_install_identity
from core.globalization.pending_updates import PendingUpdateStore
from core.globalization.runtime_paths import ensure_runtime_layout, get_runtime_paths
from core.globalization.sqlite_store import connect_cache_db, write_bundle
from core.globalization.workbook_import import refresh_from_local_sqlite_cache
from core.globalization.write_foundation import WorkbookLockManager, WorkbookSyncService


def test_metadata_loads_from_source_without_repo_cwd(tmp_path, monkeypatch) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    monkeypatch.chdir(tmp_path)
    app_metadata._load_app_metadata_cached.cache_clear()

    loaded = app_metadata.load_app_metadata(repo_root)

    assert loaded.app_name == "EOAT Atlas"
    assert loaded.release_id == "eoat-atlas-0.9.0-dev-phase-2.6"
    assert loaded.cache_schema_version == loaded.event_schema_version == loaded.config_schema_version == 1


def test_metadata_and_resources_load_from_simulated_packaged_root(tmp_path, monkeypatch) -> None:
    package_root = tmp_path / "package"
    package_root.mkdir()
    (package_root / "release_metadata.json").write_text(
        json.dumps(
            {
                "app_name": "EOAT Atlas",
                "app_version": "9.9.9-test",
                "release_id": "packaged-release",
                "build_id": "packaged-build",
                "build_date": "2026-07-10",
                "cache_schema_version": 1,
                "event_schema_version": 1,
                "config_schema_version": 1,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(package_root), raising=False)
    app_metadata._load_app_metadata_cached.cache_clear()

    loaded = app_metadata.load_app_metadata()

    assert resources.app_base_path() == package_root
    assert resources.release_metadata_path() == package_root / "release_metadata.json"
    assert loaded.app_version == "9.9.9-test"
    assert loaded.release_id == "packaged-release"


def test_runtime_folder_switches_between_dev_and_frozen_prod(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("EOAT_ATLAS_LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    assert get_runtime_paths().runtime_root == tmp_path / "local" / "EOAT_Atlas_Dev"

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.delenv("EOAT_ATLAS_DEV_RUNTIME", raising=False)
    assert get_runtime_paths().runtime_root == tmp_path / "local" / "EOAT_Atlas"


def test_runtime_artifacts_are_localappdata_only(tmp_path, monkeypatch) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("EOAT_ATLAS_LOCALAPPDATA", str(tmp_path / "local"))
    runtime = ensure_runtime_layout(get_runtime_paths())
    config = load_or_create_global_config(runtime)
    identity = load_or_create_install_identity(runtime)
    with connect_cache_db(runtime.db_path) as conn:
        write_bundle(conn, AtlasDataBundle(project_root=str(repo_root), loaded_at="phase2.6"), import_id="phase2.6", source_metadata={}, started_at="phase2.6")
    update = PendingUpdateStore(runtime, config).create_update(
        entity_type="eoat",
        entity_id="P2-6",
        field_name="status",
        expected_original_value="",
        proposed_value="Ready",
        source_view="unit_test",
        source_action="runtime_gate",
    )
    event = EventOutbox(runtime, config).create_event(
        event_type="runtime_gate",
        action="runtime_gate",
        entity_type="eoat",
        entity_id="P2-6",
        payload={
            "pending_update_ids": [update["pending_update_id"]],
            "field_changes": [{"field_name": "status", "expected_original_value": "", "proposed_value": "Ready"}],
            "validation_result": {"status": "valid"},
            "conflict_result": {"status": "none"},
            "write_result": {"status": "not_written"},
        },
    )
    refreshed = refresh_from_local_sqlite_cache(runtime)

    assert runtime.runtime_root == tmp_path / "local" / "EOAT_Atlas_Dev"
    assert runtime.install_identity_path.exists()
    assert runtime.db_path.exists()
    assert (runtime.pending_updates_dir / f"{update['pending_update_id']}.json").exists()
    assert list(runtime.event_outbox_dir.glob(f"*_{event['event_id']}.json"))
    assert identity.install_id == config.install_id
    assert refreshed.metrics["local_refresh"] is True
    assert not (repo_root / "install_identity.json").exists()
    assert not (repo_root / "data" / "local_cache.db").exists()
    assert not (repo_root / "events" / "outbox").exists()


def test_spec_is_ready_for_metadata_and_excludes_old_targets() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    spec_text = (repo_root / "EOAT_Atlas.spec").read_text(encoding="utf-8")

    assert "Path(__file__).resolve().parent" in spec_text
    assert '["packaging/eoat_atlas_entry.py"]' in spec_text
    assert "release_metadata.json" in spec_text
    assert 'name="EOAT Atlas"' in spec_text
    for forbidden in ("EOAT_Command_Center", "eoat_command_center_entry", "run_dashboard", "app.dashboard_ui", "app.atlas.atlas_window", "local_cache.db", "install_identity.json"):
        assert forbidden not in spec_text


def test_lock_and_sync_attempt_metadata_include_identity(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("EOAT_ATLAS_LOCALAPPDATA", str(tmp_path / "local"))
    runtime = ensure_runtime_layout(get_runtime_paths())
    config = load_or_create_global_config(runtime)
    lock = WorkbookLockManager(config).acquire(runtime.local_lock_diagnostics_dir, purpose="identity-test")
    try:
        lock_text = lock.path.read_text(encoding="utf-8")
    finally:
        WorkbookLockManager(config).release(lock)
    assert f"install_id={config.install_id}" in lock_text
    assert f"app_instance_id={config.app_instance_id}" in lock_text

    workbook = _simple_workbook(tmp_path)
    update = PendingUpdateStore(runtime, config).create_update(
        entity_type="eoat",
        entity_id="P4-EOAT-0001",
        field_name="Status",
        expected_original_value="Old",
        proposed_value="Ready",
        source_view="unit_test",
        source_action="identity_sync_refusal",
    )
    result = WorkbookSyncService(runtime, config).sync_pending_update_to_sandbox(
        update["pending_update_id"],
        workbook_path=workbook,
        sheet_name="EOAT Inventory",
        id_column="EOAT Assembly ID",
    )
    with connect_cache_db(runtime.db_path) as conn:
        row = conn.execute("SELECT payload_json FROM sync_attempts WHERE attempt_id = ?", (result["sync_attempt_id"],)).fetchone()
    payload = json.loads(row["payload_json"])
    assert result["status"] == "refused"
    assert payload["install_id"] == config.install_id
    assert payload["app_instance_id"] == config.app_instance_id
    assert payload["release_id"] == config.release_id


def test_preflight_script_passes() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [sys.executable, str(repo_root / "scripts" / "preflight_onedir_readiness.py")],
        cwd=repo_root,
        text=True,
        capture_output=True,
        timeout=180,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "PASS release metadata loads" in completed.stdout
    assert "PASS production writes are disabled by default" in completed.stdout


def test_package_smoke_script_fails_gracefully_when_dist_missing(tmp_path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    missing_exe = tmp_path / "dist" / "EOAT Atlas" / "EOAT Atlas.exe"
    completed = subprocess.run(
        [sys.executable, str(repo_root / "scripts" / "smoke_test_package.py"), str(missing_exe)],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        timeout=60,
    )

    assert completed.returncode == 1
    assert "packaged executable not found" in completed.stdout


def _simple_workbook(tmp_path: Path) -> Path:
    path = tmp_path / "sandbox.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "EOAT Inventory"
    sheet.append(["EOAT Assembly ID", "Status"])
    sheet.append(["P4-EOAT-0001", "Old"])
    workbook.save(path)
    workbook.close()
    return path
