from __future__ import annotations

import json

from launcher.config import ConfigLoader, LauncherConfig
from launcher.core import AppLauncher, PathResolver, ResourceChecker, SingleInstanceGuard, UpdateChecker, VersionReader
from launcher.diagnostics import DiagnosticsWriter
from launcher.repair import RepairService


def test_missing_config_is_created_from_defaults(tmp_path):
    config_path = tmp_path / "launcher_config.json"

    result = ConfigLoader(config_path).load()

    assert result.created
    assert config_path.exists()
    assert result.config.appExecutableName == "EOAT Atlas.exe"


def test_path_resolution_uses_configured_app_path(tmp_path):
    app_root = tmp_path / "EOAT Atlas"
    app_root.mkdir()
    exe = app_root / "EOAT Atlas.exe"
    exe.write_text("placeholder", encoding="utf-8")
    config = LauncherConfig(appInstallPath=str(app_root))

    resolved = PathResolver(config, ConfigLoader(tmp_path / "launcher_config.json")).resolve()

    assert resolved.found
    assert resolved.install_path == app_root
    assert resolved.executable_path == exe
    assert resolved.source == "launcher_config"


def test_path_resolution_uses_installer_current_app_metadata(tmp_path, monkeypatch):
    app_root = tmp_path / "EOAT_Atlas" / "App" / "eoat-atlas-0.9.0-dev-phase-2.6"
    app_root.mkdir(parents=True)
    exe = app_root / "EOAT Atlas.exe"
    exe.write_text("placeholder", encoding="utf-8")
    runtime_root = tmp_path / "EOAT_Atlas"
    (runtime_root / "current_app.json").write_text(
        json.dumps({"app_install_path": str(app_root), "app_exe_path": str(exe)}),
        encoding="utf-8",
    )
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    resolved = PathResolver(LauncherConfig(), ConfigLoader(tmp_path / "launcher_config.json")).resolve()

    assert resolved.found
    assert resolved.install_path == app_root
    assert resolved.executable_path == exe
    assert resolved.source == "install_metadata:current_app.json"


def test_path_resolution_uses_program_files_fallback(tmp_path, monkeypatch):
    program_files = tmp_path / "Program Files"
    app_root = program_files / "EOAT Atlas"
    app_root.mkdir(parents=True)
    exe = app_root / "EOAT Atlas.exe"
    exe.write_text("placeholder", encoding="utf-8")
    monkeypatch.setenv("PROGRAMFILES", str(program_files))
    monkeypatch.delenv("PROGRAMFILES(X86)", raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "OtherUser"))

    resolved = PathResolver(LauncherConfig(), ConfigLoader(tmp_path / "launcher_config.json")).resolve()

    assert resolved.found
    assert resolved.install_path == app_root
    assert resolved.install_mode == "it-managed"


def test_path_resolution_reports_missing_app(tmp_path):
    app_root = tmp_path / "Missing Atlas"
    config = LauncherConfig(appInstallPath=str(app_root))

    resolved = PathResolver(config, ConfigLoader(tmp_path / "launcher_config.json")).resolve()

    assert not resolved.found
    assert "not found" in resolved.message.casefold()


def test_app_launcher_starts_entry_point(tmp_path):
    script = tmp_path / "start_atlas.py"
    marker = tmp_path / "started.txt"
    script.write_text(
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('started', encoding='utf-8')\n",
        encoding="utf-8",
    )
    config = LauncherConfig(appInstallPath=str(tmp_path), appExecutableName="missing.exe", appEntryPoint=script.name)

    resolved = PathResolver(config, ConfigLoader(tmp_path / "launcher_config.json")).resolve()
    result = AppLauncher().start(resolved, config)

    assert result.started
    assert marker.read_text(encoding="utf-8") == "started"


def test_corrupt_config_is_handled_gracefully(tmp_path):
    config_path = tmp_path / "launcher_config.json"
    config_path.write_text("{not-json", encoding="utf-8")

    result = ConfigLoader(config_path).load()

    assert result.corrupt
    assert result.config.appExecutableName == "EOAT Atlas.exe"


def test_version_metadata_parsing(tmp_path):
    app_root = tmp_path / "EOAT Atlas"
    app_root.mkdir()
    (app_root / "version.json").write_text(
        json.dumps(
            {
                "appName": "EOAT Atlas",
                "version": "1.2.3",
                "buildDate": "2026-07-10",
                "buildId": "abc123",
                "channel": "stable",
            }
        ),
        encoding="utf-8",
    )

    version = VersionReader().read(app_root)

    assert version is not None
    assert version.version == "1.2.3"
    assert version.buildId == "abc123"


def test_release_metadata_parsing(tmp_path):
    app_root = tmp_path / "EOAT Atlas"
    app_root.mkdir()
    (app_root / "release_metadata.json").write_text(
        json.dumps(
            {
                "app_name": "EOAT Atlas",
                "app_version": "0.9.0-dev",
                "build_date": "2026-07-10",
                "build_id": "phase-2.6-dev",
                "environment": "development",
            }
        ),
        encoding="utf-8",
    )

    version = VersionReader().read(app_root)

    assert version is not None
    assert version.version == "0.9.0-dev"
    assert version.buildId == "phase-2.6-dev"
    assert version.channel == "development"


def test_update_checker_compares_local_manifest(tmp_path):
    manifest = tmp_path / "update_manifest.json"
    manifest.write_text(json.dumps({"version": "1.2.4"}), encoding="utf-8")
    config = LauncherConfig(updateManifestPath=str(manifest))
    version = VersionReader().read(tmp_path)
    if version is None:
        (tmp_path / "version.json").write_text(json.dumps({"version": "1.2.3"}), encoding="utf-8")
        version = VersionReader().read(tmp_path)

    result = UpdateChecker(config).check(version, install_path=tmp_path)

    assert result.update_available
    assert result.availableVersion == "1.2.4"


def test_resource_checker_handles_available_and_unavailable_paths(tmp_path):
    available = tmp_path / "available"
    available.mkdir()
    missing = tmp_path / "missing"
    config = LauncherConfig(
        allowOfflineLaunch=True,
        networkRequiredPaths=[
            {"label": "Available", "path": str(available), "required": True},
            {"label": "Missing", "path": str(missing), "required": False},
        ],
    )

    result = ResourceChecker(config).check()

    assert len(result.statuses) == 2
    assert result.statuses[0].available
    assert not result.statuses[1].available
    assert not result.blocking


def test_single_instance_guard_rejects_duplicate(tmp_path):
    first = SingleInstanceGuard("EOATAtlasLauncherTest", lock_dir=tmp_path)
    second = SingleInstanceGuard("EOATAtlasLauncherTest", lock_dir=tmp_path)
    try:
        assert first.acquire()
        assert not second.acquire()
    finally:
        first.release()
        second.release()


def test_repair_recreates_missing_config_and_records_app_path(tmp_path):
    config_path = tmp_path / "config" / "launcher_config.json"
    app_root = tmp_path / "EOAT Atlas"
    app_root.mkdir()
    (app_root / "EOAT Atlas.exe").write_text("placeholder", encoding="utf-8")
    diagnostics = DiagnosticsWriter(tmp_path / "logs")

    result = RepairService(ConfigLoader(config_path), diagnostics).repair(app_path=app_root)

    assert result.ok
    assert config_path.exists()
    data = json.loads(config_path.read_text(encoding="utf-8"))
    assert data["appInstallPath"] == str(app_root)


def test_logging_creates_expected_log_entries(tmp_path):
    diagnostics = DiagnosticsWriter(tmp_path / "logs")

    diagnostics.log_event("test_event", resolvedApp={"found": True})

    log_text = diagnostics.log_path.read_text(encoding="utf-8")
    assert "test_event" in log_text
    assert "launcherVersion" in log_text
