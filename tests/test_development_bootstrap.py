from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QLabel

import run_atlas
from app.atlas.minimalist.settings_page import MinimalistSettingsContent
from core.config import UserConfig
from core.data_gateway.configuration import GatewayConfiguration
from core.development_bootstrap import mysql_manager as mysql_module
from core.development_bootstrap.exceptions import BootstrapError
from core.development_bootstrap.mysql_manager import MySQLManager
from core.development_bootstrap.process_tracking import ProcessInfo
from core.development_bootstrap.service_manager import (
    CANONICAL_MARKER,
    BootstrapConfiguration,
    assert_module_is_canonical,
)
from core.globalization.app_metadata import load_app_metadata
from core.versioning import get_version_info


def test_canonical_marker_and_startup_root_are_resolved_from_run_atlas() -> None:
    assert Path(run_atlas.__file__).resolve().parent == run_atlas.REPOSITORY_ROOT
    assert (run_atlas.REPOSITORY_ROOT / CANONICAL_MARKER).is_file()


def test_default_development_backend_is_mysql_api(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "development.json").write_text(
        json.dumps({"environment": "development", "backend": "mysql_api", "writes_enabled": True}),
        encoding="utf-8",
    )
    for key in ("EOAT_ATLAS_DATA_BACKEND", "EOAT_ATLAS_ENVIRONMENT", "EOAT_ATLAS_WRITES_ENABLED"):
        monkeypatch.delenv(key, raising=False)

    resolved = BootstrapConfiguration.resolve(tmp_path)

    assert resolved.backend == "mysql_api"
    assert resolved.environment == "development"
    assert resolved.writes_enabled is True
    assert GatewayConfiguration.from_environment().backend == "mysql_api"


def test_legacy_backend_requires_explicit_selection(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "development.json").write_text("{}", encoding="utf-8")
    monkeypatch.delenv("EOAT_ATLAS_DATA_BACKEND", raising=False)
    assert BootstrapConfiguration.resolve(tmp_path).backend == "mysql_api"
    assert BootstrapConfiguration.resolve(tmp_path, backend="legacy").backend == "legacy"


def test_import_path_isolation_removes_old_repository_copy(tmp_path: Path, monkeypatch) -> None:
    old = tmp_path / "old-repository-copy"
    old.mkdir()
    (old / CANONICAL_MARKER).write_text("synthetic marker", encoding="utf-8")
    neutral = r"C:\Python\Lib"
    monkeypatch.setattr(sys, "path", [str(old), neutral])

    run_atlas._isolate_import_path()

    assert sys.path[0] == str(run_atlas.REPOSITORY_ROOT)
    assert str(old) not in sys.path
    assert neutral in sys.path


def test_loaded_module_guard_rejects_another_repository(tmp_path: Path) -> None:
    module = SimpleNamespace(__file__=str(tmp_path / "app" / "main.py"))
    with pytest.raises(BootstrapError, match="outside the canonical repository"):
        assert_module_is_canonical(module, run_atlas.REPOSITORY_ROOT)


def test_version_sources_agree() -> None:
    root = run_atlas.REPOSITORY_ROOT
    canonical = get_version_info(root)
    metadata = load_app_metadata(root)
    atlas_version = json.loads((root / "app" / "atlas" / "version.json").read_text(encoding="utf-8"))

    assert canonical.application_version == metadata.app_version == atlas_version["version"]
    assert re.fullmatch(r"\d+\.\d+\.\d+", canonical.application_version)
    assert canonical.build_id == metadata.build_id
    assert "buildId" not in atlas_version
    assert canonical.build_id.startswith(f"eoat-atlas-{canonical.application_version}-")
    assert canonical.release_id == metadata.release_id == f"eoat-atlas-{canonical.application_version}"


def test_wrong_process_on_mysql_port_is_never_stopped(monkeypatch) -> None:
    manager = MySQLManager()
    monkeypatch.setattr(mysql_module, "listener_pid", lambda _port: 42)
    monkeypatch.setattr(
        mysql_module,
        "process_info",
        lambda _pid: ProcessInfo(42, "unrelated.exe", r"C:\Other\unrelated.exe", "unrelated.exe"),
    )

    with pytest.raises(BootstrapError, match="unexpected process"):
        manager.status()


def test_stale_schema_fails_closed_with_authorized_migrator_guidance() -> None:
    manager = MySQLManager()
    stale = mysql_module.MySQLStatus(
        running=True,
        connected=True,
        pid=42,
        version="8.4.9",
        database="eoat_atlas_dev",
        schema_revision="20260714_0005",
        table_count=52,
        log_path="mysql.log",
    )

    with pytest.raises(BootstrapError) as captured:
        manager.verify(stale)

    rendered = captured.value.render()
    assert "Expected schema: 20260721_0008" in rendered
    assert "Detected schema: 20260714_0005" in rendered
    assert "authorized migrator" in rendered
    assert "runtime credentials never migrate schemas" in rendered


def test_desktop_runtime_modules_do_not_import_mysql_driver() -> None:
    root = run_atlas.REPOSITORY_ROOT
    files = [*root.joinpath("app").rglob("*.py"), *root.joinpath("core", "data_gateway").rglob("*.py")]
    source = "\n".join(path.read_text(encoding="utf-8") for path in files)
    assert "import pymysql" not in source
    assert "from sqlalchemy" not in source


def test_mysql_api_diagnostics_hide_legacy_operational_fields(qapp, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("EOAT_ATLAS_DATA_BACKEND", "mysql_api")
    monkeypatch.setenv("EOAT_ATLAS_USER_DATA_DIR", str(tmp_path / "settings"))
    metrics = {
        "backend": "mysql_api",
        "environment": "development",
        "api_online": True,
        "api_url": "http://127.0.0.1:8765",
        "api_version": "1.4.0",
        "api_response_ms": 3.2,
        "database_connected": True,
        "mysql_version": "8.4.9",
        "schema_revision": "20260721_0008",
        "required_schema_revision": "20260721_0008",
        "server_revision": "test",
        "cache_path": str(tmp_path / "eoat_atlas_api_cache_dev.db"),
        "cache_schema_version": "3",
        "cached_counts": {"eoats": 1},
        "writes_enabled": True,
        "offline_read_only": False,
        "legacy_fallback": False,
    }
    monkeypatch.setattr(MinimalistSettingsContent, "_mysql_api_metrics", lambda self: metrics)
    controller = SimpleNamespace(
        config=UserConfig(project_root=str(tmp_path)),
        minimalist_app_settings={},
        deep_refresh_data=lambda: None,
    )
    content = MinimalistSettingsContent(controller)
    content.select_section("diagnostics_support")
    qapp.processEvents()
    text = "\n".join(label.text() for label in content.main_panel.findChildren(QLabel))

    assert "MySQL server version" in text
    assert "Disposable API cache" in text
    assert "Legacy fallback" in text
    assert "Master workbook" not in text
    assert "Event outbox" not in text
    assert "Lock status" not in text
