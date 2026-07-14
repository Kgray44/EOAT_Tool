from __future__ import annotations

import json
from pathlib import Path

from openpyxl import Workbook

from core.atlas_data_loader import _load_atlas_data_uncached
from core.globalization.config import load_or_create_global_config
from core.globalization.events import EventOutbox, GlobalEventWriter
from core.globalization.pending_updates import PendingUpdateStore
from core.globalization.runtime_paths import ensure_runtime_layout, get_runtime_paths
from core.globalization.sqlite_store import cache_metadata, connect_cache_db
from core.globalization.workbook_import import load_atlas_data_from_sqlite_cache
from core.globalization.write_foundation import ChangeValidationService, WorkbookLockManager, WorkbookUpdateService
from core.paths import resolve_project_paths
from tests.fixtures.fake_project import create_fake_eoat_project
from tests.fixtures.reference_workbooks import create_press_reference_workbooks


def test_runtime_paths_and_config_are_created_under_development_localappdata(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("EOAT_ATLAS_LOCALAPPDATA", str(tmp_path))

    runtime = ensure_runtime_layout(get_runtime_paths())
    config = load_or_create_global_config(runtime)
    loaded_again = load_or_create_global_config(runtime)

    assert runtime.runtime_root == tmp_path / "EOAT_Atlas_Dev"
    assert runtime.db_path.parent.exists()
    assert runtime.pending_updates_dir.exists()
    assert runtime.event_outbox_dir.exists()
    assert runtime.event_written_dir.exists()
    assert runtime.event_failed_dir.exists()
    assert runtime.install_identity_path.exists()
    assert runtime.settings_path.exists()
    assert config.config_schema_version == 1
    assert config.environment == "development"
    assert config.write_mode == "disabled"
    assert config.network_root
    assert config.event_log_path
    assert config.backup_path
    assert config.lock_path
    assert config.refresh_interval_seconds == 60
    assert config.app_instance_id == loaded_again.app_instance_id


def test_sqlite_import_stages_workbook_and_reuses_cache_offline(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("EOAT_ATLAS_LOCALAPPDATA", str(tmp_path / "local"))
    project = create_fake_eoat_project(tmp_path / "project")
    paths = resolve_project_paths(project)
    create_press_reference_workbooks(paths.reference_data)
    source_paths = _source_paths(project)

    bundle = load_atlas_data_from_sqlite_cache(
        project,
        force_refresh=True,
        exclude_unaudited_tools=True,
        source_paths=source_paths,
        legacy_loader=_load_atlas_data_uncached,
    )

    runtime = get_runtime_paths()
    assert runtime.db_path.exists()
    assert len(bundle.eoats) == 3
    assert bundle.metrics["sqlite_cache_refreshed"] is True
    with connect_cache_db(runtime.db_path) as conn:
        metadata = cache_metadata(conn)
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        source_columns = {row["name"] for row in conn.execute("PRAGMA table_info(source_files)").fetchall()}
    copied_to = metadata["source_files"]["eoat_master_tracker"]["copied_to"]
    assert str(runtime.workbook_staging_dir) in copied_to
    assert copied_to.endswith("EOAT_Master_Tracker.xlsx")
    assert metadata["source_files"]["eoat_master_tracker"]["sha256"]
    assert {
        "schema_migrations",
        "app_metadata",
        "source_files",
        "import_runs",
        "eoats",
        "tools",
        "machines",
        "compatibility",
        "photos",
        "documents",
        "event_log",
        "pending_updates",
        "sync_attempts",
        "conflicts",
    }.issubset(tables)
    assert "sha256" in source_columns

    offline_paths = {**source_paths, "eoat_master_tracker": str(tmp_path / "missing.xlsx")}
    cached = load_atlas_data_from_sqlite_cache(
        project,
        force_refresh=False,
        exclude_unaudited_tools=True,
        source_paths=offline_paths,
        legacy_loader=_load_atlas_data_uncached,
    )

    assert len(cached.eoats) == 3
    assert cached.metrics["sqlite_cache_hit"] is True
    assert cached.metrics["local_refresh"] is True
    assert cached.metrics["deep_refresh"] is False


def test_pending_updates_survive_cache_rebuild_and_reindex(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("EOAT_ATLAS_LOCALAPPDATA", str(tmp_path / "local"))
    project = create_fake_eoat_project(tmp_path / "project")
    paths = resolve_project_paths(project)
    create_press_reference_workbooks(paths.reference_data)
    runtime = ensure_runtime_layout(get_runtime_paths())
    config = load_or_create_global_config(runtime)
    store = PendingUpdateStore(runtime, config)
    update = store.create_update(
        entity_type="eoat",
        entity_id="P4-EOAT-0056",
        field="Current Machine",
        original_value="Not Installed",
        proposed_value="23",
    )

    load_atlas_data_from_sqlite_cache(
        project,
        force_refresh=True,
        exclude_unaudited_tools=True,
        source_paths=_source_paths(project),
        legacy_loader=_load_atlas_data_uncached,
    )

    assert (runtime.pending_updates_dir / f"{update['update_id']}.json").exists()
    assert update["event_id"]
    assert update["event_log_status"] == "event_pending"
    assert update["workbook_sync_status"] == "not_started"
    with connect_cache_db(runtime.db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM pending_updates").fetchone()[0]
    assert count == 1


def test_event_outbox_delivers_only_to_sandbox(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("EOAT_ATLAS_LOCALAPPDATA", str(tmp_path / "local"))
    runtime = ensure_runtime_layout(get_runtime_paths())
    config = load_or_create_global_config(runtime)
    event = EventOutbox(runtime, config).create_event(action="update_requested", entity_type="eoat", entity_id="P4-EOAT-0001")
    event_path = next(runtime.event_outbox_dir.glob(f"*_{event['event_id']}.json"))
    delivered = GlobalEventWriter(config).deliver_sandbox_event(
        event_path,
        tmp_path / "sandbox_events",
    )

    assert delivered.exists()
    assert json.loads(delivered.read_text(encoding="utf-8"))["event_id"] == event["event_id"]
    assert event["app_instance_id"] == config.app_instance_id
    assert event["computer_name"] == config.computer_name


def test_lock_manager_competition_and_disabled_write_refusal(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("EOAT_ATLAS_LOCALAPPDATA", str(tmp_path / "local"))
    config = load_or_create_global_config(ensure_runtime_layout(get_runtime_paths()))
    manager = WorkbookLockManager(config)
    lock = manager.acquire(tmp_path / "locks", purpose="unit-test")

    try:
        try:
            manager.acquire(tmp_path / "locks", purpose="second-instance", attempts=1)
        except TimeoutError:
            competed = True
        else:
            competed = False
        assert competed
    finally:
        manager.release(lock)

    valid, message = ChangeValidationService(config).validate_submission(
        {"entity_type": "eoat", "entity_id": "P4-EOAT-0001", "field": "Status", "proposed_value": "Ready"}
    )
    assert valid is True
    assert "validated" in message.casefold()
    assert WorkbookUpdateService(config).apply_shadow_update(_simple_workbook(tmp_path), sheet_name="Data", row_number=2, field_name="Status", proposed_value="Ready")["status"] == "refused"


def _source_paths(project: Path) -> dict[str, str]:
    paths = resolve_project_paths(project)
    return {
        "eoat_master_tracker": str(paths.master_workbook),
        "press_capacity_workbook": str(paths.reference_data / "press_capacity.xlsx"),
        "robot_workbook": str(paths.robot_info_workbook),
        "photos_root": str(paths.cell_photos),
        "output_folder": str(paths.final_handoff / "Atlas_Exports"),
        "reference_docs_folder": str(paths.standards),
    }


def _simple_workbook(tmp_path: Path) -> Path:
    path = tmp_path / "sandbox.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Data"
    sheet.append(["ID", "Status"])
    sheet.append(["P4-EOAT-0001", "Old"])
    workbook.save(path)
    return path
