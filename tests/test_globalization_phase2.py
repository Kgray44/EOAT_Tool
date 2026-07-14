from __future__ import annotations

import os
import importlib.util
from pathlib import Path

from core.atlas_data_loader import _load_atlas_data_uncached, load_atlas_data
from core.atlas_search import resolve_search_query, search_atlas
from core.atlas_setup_packets import build_setup_packet_context
from core.fit_check_service import FitCheckRequest, run_fit_check
from core.globalization.config import NETWORK_ROOT, load_or_create_global_config
from core.globalization.pending_updates import PendingUpdateStore, detect_pending_update_conflicts
from core.globalization.repositories import EOATRepository
from core.globalization.runtime_paths import ensure_runtime_layout, get_runtime_paths
from core.globalization.sqlite_store import cache_metadata, connect_cache_db
from core.globalization.workbook_import import load_atlas_data_from_sqlite_cache
from core.globalization.write_foundation import (
    ConflictDetectionService,
    SyncAttemptLogger,
    WorkbookLockManager,
)
from core.paths import resolve_project_paths
from tests.fixtures.fake_project import create_fake_eoat_project
from tests.fixtures.reference_workbooks import create_press_reference_workbooks


def test_atlas_runtime_settings_and_startup_project_root_are_globalized(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("EOAT_ATLAS_LOCALAPPDATA", str(tmp_path / "local"))

    from app.atlas.main import _load_globalized_user_config
    from app.atlas.minimalist.data import recent_searches_path
    from app.atlas.minimalist.settings_store import admin_auth_path, settings_path
    from app.atlas.settings import atlas_settings_path

    runtime = ensure_runtime_layout(get_runtime_paths())
    config = _load_globalized_user_config()

    assert runtime.runtime_root == tmp_path / "local" / "EOAT_Atlas_Dev"
    assert Path(config.project_root) == NETWORK_ROOT
    global_config = load_or_create_global_config(runtime)
    assert global_config.product_name == "EOAT Atlas"
    assert global_config.product_scope_note == "minimalist/current EOAT Atlas only"
    assert global_config.active_ui_mode == "minimalist"
    assert global_config.release_entry_point == "packaging/eoat_atlas_entry.py"
    for path in (atlas_settings_path(), settings_path(), admin_auth_path(), recent_searches_path()):
        assert runtime.runtime_root in path.parents


def test_release_target_is_minimalist_atlas_only() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    from app.atlas.main import _extract_ui_mode

    entry_path = repo_root / "packaging" / "eoat_atlas_entry.py"
    spec_path = repo_root / "EOAT_Atlas.spec"
    build_script = repo_root / "scripts" / "build_package.py"
    smoke_script = repo_root / "scripts" / "smoke_test_package.py"

    module_spec = importlib.util.spec_from_file_location("eoat_atlas_entry_guard", entry_path)
    assert module_spec is not None and module_spec.loader is not None
    entry_module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(entry_module)

    assert _extract_ui_mode(["atlas.exe"]) == "minimalist"
    assert _extract_ui_mode(["atlas.exe", "--ui", "classic"]) == "minimalist"
    assert entry_module._force_minimalist_ui(["atlas.exe", "--ui", "classic"]) == ["atlas.exe", "--ui=minimalist"]

    spec_text = spec_path.read_text(encoding="utf-8")
    build_text = build_script.read_text(encoding="utf-8")
    smoke_text = smoke_script.read_text(encoding="utf-8")
    entry_text = entry_path.read_text(encoding="utf-8")

    assert '["packaging/eoat_atlas_entry.py"]' in spec_text
    assert 'name="EOAT Atlas"' in spec_text
    assert "EOAT_Command_Center.spec" not in build_text
    assert "EOAT_Atlas.spec" in build_text
    assert "dist\" / \"EOAT Atlas\" / \"EOAT Atlas.exe" in smoke_text
    assert "EOAT_ATLAS_SMOKE_TEST" in smoke_text
    assert "app.main" not in entry_text
    assert 'collect_submodules("app.pages")' not in spec_text
    assert 'collect_submodules("app.atlas")' not in spec_text
    assert "eoat_command_center_entry" not in spec_text
    assert "app.dashboard_ui" not in spec_text
    assert "app.atlas.atlas_window" not in spec_text


def test_sqlite_cache_is_normal_read_path_for_navigation_search_profile_and_fit_check(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("EOAT_ATLAS_LOCALAPPDATA", str(tmp_path / "local"))
    project = _project_with_sources(tmp_path / "shared")
    source_paths = _source_paths(project)
    calls = {"legacy_loader": 0}

    def counting_loader(*args, **kwargs):
        calls["legacy_loader"] += 1
        return _load_atlas_data_uncached(*args, **kwargs)

    first = load_atlas_data_from_sqlite_cache(
        project,
        force_refresh=True,
        exclude_unaudited_tools=True,
        source_paths=source_paths,
        legacy_loader=counting_loader,
    )
    monkeypatch.setattr(
        "core.atlas_data_loader._load_atlas_data_uncached",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("Workbook loader should not run on cache hit.")),
    )
    cached = load_atlas_data(
        project,
        force_refresh=False,
        exclude_unaudited_tools=True,
        source_paths=source_paths,
    )

    eoat = _representative_eoat(cached)
    tool = _representative_tool(cached)
    machine = _representative_machine(cached)
    before_operations = calls["legacy_loader"]

    assert len(first.eoats) == len(cached.eoats)
    assert cached.metrics["sqlite_cache_hit"] is True
    assert before_operations == 1
    assert resolve_search_query(cached, eoat.eoat_id).found is True
    assert search_atlas(cached, tool.tool)
    assert build_setup_packet_context(cached, machine.machine, tool.tool, eoat.eoat_id).eoat_id == eoat.eoat_id
    assert run_fit_check(
        cached,
        FitCheckRequest(tool_id=tool.tool, machine_id=machine.machine, eoat_id=eoat.eoat_id),
    ) is not None
    assert calls["legacy_loader"] == before_operations


def test_workbook_loader_and_sqlite_cache_parity_for_core_atlas_data(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("EOAT_ATLAS_LOCALAPPDATA", str(tmp_path / "local"))
    project = _project_with_sources(tmp_path / "shared")
    source_paths = _source_paths(project)

    workbook_bundle = _load_atlas_data_uncached(
        project,
        exclude_unaudited_tools=True,
        source_paths=source_paths,
    )
    load_atlas_data_from_sqlite_cache(
        project,
        force_refresh=True,
        exclude_unaudited_tools=True,
        source_paths=source_paths,
        legacy_loader=_load_atlas_data_uncached,
    )
    sqlite_bundle = load_atlas_data_from_sqlite_cache(
        project,
        force_refresh=False,
        exclude_unaudited_tools=True,
        source_paths=source_paths,
        legacy_loader=_load_atlas_data_uncached,
    )

    assert len(sqlite_bundle.eoats) == len(workbook_bundle.eoats)
    assert len(sqlite_bundle.tools) == len(workbook_bundle.tools)
    assert len(sqlite_bundle.machines) == len(workbook_bundle.machines)
    assert sorted(record.eoat_id for record in sqlite_bundle.eoats) == sorted(record.eoat_id for record in workbook_bundle.eoats)
    assert [_eoat_snapshot(record) for record in sqlite_bundle.eoats] == [_eoat_snapshot(record) for record in workbook_bundle.eoats]
    assert [_tool_snapshot(record) for record in sqlite_bundle.tools] == [_tool_snapshot(record) for record in workbook_bundle.tools]
    assert [_machine_snapshot(record) for record in sqlite_bundle.machines] == [_machine_snapshot(record) for record in workbook_bundle.machines]
    assert sorted(_compatibility_rows(sqlite_bundle)) == sorted(_compatibility_rows(workbook_bundle))

    queries = [
        _representative_eoat(workbook_bundle).eoat_id,
        _representative_tool(workbook_bundle).tool,
        _representative_machine(workbook_bundle).machine,
        "demo housing",
    ]
    assert [_search_snapshot(sqlite_bundle, query) for query in queries] == [_search_snapshot(workbook_bundle, query) for query in queries]

    eoat = _representative_eoat(workbook_bundle)
    tool = _representative_tool(workbook_bundle)
    machine = _representative_machine(workbook_bundle)
    assert _fit_snapshot(sqlite_bundle, tool.tool, machine.machine, eoat.eoat_id) == _fit_snapshot(
        workbook_bundle,
        tool.tool,
        machine.machine,
        eoat.eoat_id,
    )
    assert _profile_snapshot(sqlite_bundle, machine.machine, tool.tool, eoat.eoat_id) == _profile_snapshot(
        workbook_bundle,
        machine.machine,
        tool.tool,
        eoat.eoat_id,
    )


def test_pending_update_overlay_survives_restart_and_marks_effective_records(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("EOAT_ATLAS_LOCALAPPDATA", str(tmp_path / "local"))
    project = _project_with_sources(tmp_path / "shared")
    source_paths = _source_paths(project)
    runtime = ensure_runtime_layout(get_runtime_paths())
    config = load_or_create_global_config(runtime)
    bundle = load_atlas_data_from_sqlite_cache(
        project,
        force_refresh=True,
        exclude_unaudited_tools=True,
        source_paths=source_paths,
        legacy_loader=_load_atlas_data_uncached,
    )
    eoat_id = _representative_eoat(bundle).eoat_id

    store = PendingUpdateStore(runtime, config)
    update = store.create_update(
        entity_type="eoat",
        entity_id=eoat_id,
        field="status",
        original_value="Old",
        proposed_value="Needs Review",
        reason="unit test",
    )
    restarted_store = PendingUpdateStore(ensure_runtime_layout(get_runtime_paths()), load_or_create_global_config())
    effective = EOATRepository(runtime.db_path).effective_get(eoat_id)
    export_path = restarted_store.export_updates(runtime.temp_dir / "pending_updates_export.json")

    assert any(item["update_id"] == update["update_id"] for item in restarted_store.list_active_updates())
    assert effective is not None
    assert effective["status"] == "Needs Review"
    assert effective["_pending_status"] == "pending"
    assert "status" in effective["_pending_fields"]
    assert export_path.exists()
    assert resolve_project_paths(project).master_workbook.stat().st_size > 0


def test_multi_instance_runtime_roots_pending_conflicts_offline_and_stale_locks(tmp_path, monkeypatch) -> None:
    shared_project = _project_with_sources(tmp_path / "shared")
    source_paths = _source_paths(shared_project)

    runtime_a = _load_for_instance(tmp_path / "EOAT_Atlas_Instance_A", monkeypatch, shared_project, source_paths)
    runtime_b = _load_for_instance(tmp_path / "EOAT_Atlas_Instance_B", monkeypatch, shared_project, source_paths)
    assert runtime_a.runtime_root != runtime_b.runtime_root
    assert runtime_a.db_path.exists()
    assert runtime_b.db_path.exists()

    monkeypatch.setenv("EOAT_ATLAS_LOCALAPPDATA", str(tmp_path / "EOAT_Atlas_Instance_A"))
    config_a = load_or_create_global_config(ensure_runtime_layout(get_runtime_paths()))
    eoat_id = _representative_eoat(_read_cached_bundle(runtime_a)).eoat_id
    store_a = PendingUpdateStore(runtime_a, config_a)
    store_a.create_update(entity_type="eoat", entity_id=eoat_id, field="status", original_value="Clean", proposed_value="Needs Review")
    store_a.create_update(entity_type="eoat", entity_id=eoat_id, field="known_issues", original_value="", proposed_value="Inspect tubing")
    assert len(PendingUpdateStore(runtime_b, load_or_create_global_config(runtime_b)).list_updates()) == 0

    with connect_cache_db(runtime_b.db_path) as held_b_connection:
        monkeypatch.setenv("EOAT_ATLAS_LOCALAPPDATA", str(tmp_path / "EOAT_Atlas_Instance_A"))
        refreshed = load_atlas_data_from_sqlite_cache(
            shared_project,
            force_refresh=True,
            exclude_unaudited_tools=True,
            source_paths=source_paths,
            legacy_loader=_load_atlas_data_uncached,
        )
        assert held_b_connection.execute("SELECT COUNT(*) FROM eoats").fetchone()[0] == len(refreshed.eoats)

    effective = EOATRepository(runtime_a.db_path).effective_get(eoat_id, pending_dir=runtime_a.pending_updates_dir)
    assert effective is not None
    assert {"status", "known_issues"}.issubset(set(effective["_pending_fields"]))
    assert effective["_pending_conflicts"] == ()

    store_a.create_update(entity_type="eoat", entity_id=eoat_id, field="status", original_value="Clean", proposed_value="Ready")
    conflicts = detect_pending_update_conflicts(store_a.list_active_updates())
    assert len(conflicts) == 1
    assert conflicts[0]["field"] == "status"

    offline_paths = {**source_paths, "eoat_master_tracker": str(tmp_path / "missing_master.xlsx")}
    offline = load_atlas_data_from_sqlite_cache(
        shared_project,
        force_refresh=False,
        exclude_unaudited_tools=True,
        source_paths=offline_paths,
        legacy_loader=_load_atlas_data_uncached,
    )
    assert offline.metrics["sqlite_cache_hit"] is True
    assert offline.metrics["local_refresh"] is True
    assert offline.metrics["deep_refresh"] is False

    lock_manager = WorkbookLockManager(config_a, stale_after_seconds=1)
    lock = lock_manager.acquire(tmp_path / "locks", purpose="first")
    old_time = lock.path.stat().st_mtime - 10
    os.utime(lock.path, (old_time, old_time))
    stale_metadata = lock_manager.lock_metadata(tmp_path / "locks")
    replacement = lock_manager.acquire(tmp_path / "locks", purpose="second", attempts=1)
    try:
        assert stale_metadata["stale"] == "true"
        assert "process_id" in lock_manager.lock_metadata(tmp_path / "locks")
    finally:
        lock_manager.release(replacement)


def test_conflict_and_sync_attempt_foundation_records_to_sqlite(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("EOAT_ATLAS_LOCALAPPDATA", str(tmp_path / "local"))
    runtime = ensure_runtime_layout(get_runtime_paths())
    conflict = ConflictDetectionService().detect_field_conflict(
        entity_type="eoat",
        entity_id="P4-EOAT-0001",
        field="status",
        base_value="Clean",
        local_value="Needs Review",
        workbook_value="Ready",
    )
    assert conflict is not None

    with connect_cache_db(runtime.db_path) as conn:
        conflict_id = ConflictDetectionService().record_conflict(conn, conflict, update_id="update-1")
        attempt_id = SyncAttemptLogger().record(
            conn,
            status="failed",
            update_id="update-1",
            message="sandbox failure",
            payload={"reason": "unit test"},
        )
        conflict_count = conn.execute("SELECT COUNT(*) FROM conflicts WHERE conflict_id = ?", (conflict_id,)).fetchone()[0]
        attempt_count = conn.execute("SELECT COUNT(*) FROM sync_attempts WHERE attempt_id = ?", (attempt_id,)).fetchone()[0]

    assert conflict_count == 1
    assert attempt_count == 1


def _project_with_sources(root: Path) -> Path:
    project = create_fake_eoat_project(root)
    create_press_reference_workbooks(resolve_project_paths(project).reference_data)
    return project


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


def _load_for_instance(base: Path, monkeypatch, project: Path, source_paths: dict[str, str]):
    monkeypatch.setenv("EOAT_ATLAS_LOCALAPPDATA", str(base))
    load_atlas_data_from_sqlite_cache(
        project,
        force_refresh=True,
        exclude_unaudited_tools=True,
        source_paths=source_paths,
        legacy_loader=_load_atlas_data_uncached,
    )
    return get_runtime_paths()


def _read_cached_bundle(runtime):
    with connect_cache_db(runtime.db_path) as conn:
        from core.globalization.sqlite_store import read_bundle

        bundle = read_bundle(conn)
    assert bundle is not None
    return bundle


def _representative_eoat(bundle):
    return next(record for record in bundle.eoats if record.tools and record.machines)


def _representative_tool(bundle):
    return next(record for record in bundle.tools if record.compatible_eoats or record.compatible_machines)


def _representative_machine(bundle):
    return next(record for record in bundle.machines if record.compatible_eoats or record.compatible_tools)


def _eoat_snapshot(record) -> tuple:
    return (
        record.eoat_id,
        record.display_id,
        record.tools,
        record.machines,
        record.part_description,
        record.eoat_type,
        record.status,
        record.documentation.score,
        record.photo_count,
    )


def _tool_snapshot(record) -> tuple:
    return (record.tool, record.label, record.compatible_eoats, record.compatible_machines, record.part_description)


def _machine_snapshot(record) -> tuple:
    return (
        record.machine,
        record.label,
        record.compatible_eoats,
        record.compatible_tools,
        record.current_eoat,
        record.robot_type,
        record.robot_model,
    )


def _compatibility_rows(bundle) -> list[tuple[str, str, str]]:
    rows = []
    for eoat in bundle.eoats:
        for tool in eoat.tools or ("",):
            for machine in eoat.machines or ("",):
                rows.append((eoat.eoat_id, tool, machine))
    return rows


def _search_snapshot(bundle, query: str) -> tuple:
    resolution = resolve_search_query(bundle, query)
    matches = search_atlas(bundle, query, limit=4)
    return (
        resolution.found,
        resolution.entity_type,
        resolution.entity_id,
        tuple((match.result_type, match.key, match.title) for match in matches),
    )


def _fit_snapshot(bundle, tool_id: str, machine_id: str, eoat_id: str) -> tuple:
    result = run_fit_check(bundle, FitCheckRequest(tool_id=tool_id, machine_id=machine_id, eoat_id=eoat_id))
    assert result is not None
    return (
        result.status,
        result.confidence,
        result.compatibility.tool_machine,
        result.compatibility.tool_eoat,
        result.compatibility.machine_eoat,
        result.compatibility.full_setup,
    )


def _profile_snapshot(bundle, machine_id: str, tool_id: str, eoat_id: str) -> tuple:
    context = build_setup_packet_context(bundle, machine_id, tool_id, eoat_id)
    return (
        context.machine_id,
        context.tool_id,
        context.eoat_id,
        context.validation.status,
        context.documentation_score,
        context.photo_count,
        tuple((status.label, status.path, status.available) for status in bundle.source_statuses),
    )
