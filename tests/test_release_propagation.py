from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from core.data_gateway.gateway import AtlasDataGateway
from core.logging import activity_log_path, log_activity_event
from core.reporting.pdf_footer import apply_pdf_release_metadata
from core.versioning import (
    EXPECTED_API_VERSION,
    EXPECTED_SCHEMA_REVISION,
    ReleaseContextFilter,
    get_release_info,
)
from launcher.config import LauncherConfig
from launcher.core import UpdateChecker
from launcher.core import VersionInfo as LauncherVersionInfo
from release_tools.manifest import validate_manifest
from release_tools.versioning import Version, build_identifier, validate_version_sources
from scripts.publish_release import _read_source_metadata, _target_metadata
from server.eoat_api.app import version as api_version
from server.eoat_api.database import models as db
from server.eoat_api.release_provenance import ensure_application_release


def test_unified_release_info_loads_without_gui_mysql_or_network() -> None:
    info = get_release_info()
    canonical = json.loads((Path(__file__).resolve().parents[1] / "app/atlas/version.json").read_text(encoding="utf-8"))
    assert info.application_version == canonical["version"]
    assert info.release_id == f"eoat-atlas-{info.application_version}"
    assert info.api_contract_version == EXPECTED_API_VERSION
    assert info.database_schema_revision == EXPECTED_SCHEMA_REVISION
    assert info.launcher_version == "0.1.0"
    assert info.installer_version == "0.1.0"


def test_api_reports_application_api_and_schema_versions_separately() -> None:
    info = get_release_info()
    payload = api_version()
    assert payload["application_version"] == info.application_version
    assert payload["release_id"] == info.release_id
    assert payload["build_id"] == info.build_id
    assert payload["api_contract_version"] == EXPECTED_API_VERSION
    assert payload["database_schema_revision"] == EXPECTED_SCHEMA_REVISION
    assert payload["application_version"] != payload["api_contract_version"]


def test_mysql_models_preserve_ids_and_attach_release_provenance() -> None:
    release_fk = next(iter(db.ApplicationInstance.__table__.c.application_release_id.foreign_keys))
    history_fk = next(iter(db.EntityHistoryEvent.__table__.c.application_release_id.foreign_keys))
    audit_fk = next(iter(db.ChangeAuditLog.__table__.c.application_release_id.foreign_keys))
    import_fk = next(iter(db.ImportBatch.__table__.c.application_release_id.foreign_keys))
    assert release_fk.target_fullname == "application_releases.id"
    assert history_fk.target_fullname == audit_fk.target_fullname == import_fk.target_fullname
    assert db.ApplicationInstance.__table__.c.instance_uuid.unique is True
    assert "application_release_id" not in db.EOAT.__table__.primary_key.columns
    assert "application_release_id" not in db.Tool.__table__.primary_key.columns
    assert "application_release_id" not in db.Machine.__table__.primary_key.columns
    expected_indexes = {
        "ix_application_instances_application_release",
        "ix_import_batches_application_release",
        "ix_entity_history_events_application_release",
        "ix_change_audit_log_application_release",
    }
    actual_indexes = {
        index.name
        for table in (
            db.ApplicationInstance.__table__,
            db.ImportBatch.__table__,
            db.EntityHistoryEvent.__table__,
            db.ChangeAuditLog.__table__,
        )
        for index in table.indexes
    }
    assert expected_indexes <= actual_indexes


def test_mysql_release_registration_stores_canonical_release_snapshot() -> None:
    class FakeSession:
        def __init__(self):
            self.added = []

        def scalar(self, _query):
            return None

        def add(self, record):
            self.added.append(record)

        def flush(self):
            self.added[-1].id = 41

    session = FakeSession()
    info = get_release_info()
    record = ensure_application_release(session, info.provenance())
    assert record.id == 41
    assert record.application_version == info.application_version
    assert record.release_id == info.release_id
    assert record.build_id == info.build_id
    assert record.database_schema_revision == EXPECTED_SCHEMA_REVISION


def test_gateway_registration_automatically_supplies_release_identity() -> None:
    captured = {}

    def send(method, path, payload):
        captured.update({"method": method, "path": path, "payload": payload})
        return payload

    gateway = SimpleNamespace(_server_first_write=send)
    stable_id = "11111111-1111-1111-1111-111111111111"
    result = AtlasDataGateway.register_application_instance(
        gateway,
        {"instance_uuid": stable_id, "computer_name": "TEST-PC"},
    )
    info = get_release_info()
    assert result["instance_uuid"] == stable_id
    assert result["application_version"] == info.application_version
    assert result["release_id"] == info.release_id
    assert result["build_id"] == info.build_id


def test_activity_and_standard_logging_include_release_context(tmp_path: Path) -> None:
    assert log_activity_event(tmp_path, "test", {"stable_entity_id": "EOAT-123"}) is None
    entry = json.loads(activity_log_path(tmp_path).read_text(encoding="utf-8").splitlines()[-1])
    info = get_release_info()
    assert entry["application_version"] == info.application_version
    assert entry["release_id"] == info.release_id
    assert entry["build_id"] == info.build_id
    assert entry["stable_entity_id"] == "EOAT-123"

    record = logging.LogRecord("test", logging.INFO, __file__, 1, "message", (), None)
    assert ReleaseContextFilter().filter(record) is True
    assert record.application_version == info.application_version
    assert record.release_id == info.release_id


def test_pdf_metadata_contains_release_identity() -> None:
    values = {}
    canvas = SimpleNamespace(
        setCreator=lambda value: values.setdefault("creator", value),
        setAuthor=lambda value: values.setdefault("author", value),
        setSubject=lambda value: values.setdefault("subject", value),
        setKeywords=lambda value: values.setdefault("keywords", value),
    )
    apply_pdf_release_metadata(canvas)
    info = get_release_info()
    assert info.application_version in values["creator"]
    assert info.release_id in values["subject"]
    assert info.build_id in values["keywords"]


def test_installer_windows_and_repository_metadata_match_canonical() -> None:
    root = Path(__file__).resolve().parents[1]
    info = get_release_info(root)
    installer = json.loads((root / "installer" / "installer_config.json").read_text(encoding="utf-8"))
    assert installer["expected_metadata_file"] == "release_metadata.json"
    assert validate_version_sources(root) == Version.parse(info.application_version)


def test_manifest_carries_release_and_build_identity() -> None:
    info = get_release_info()
    manifest = {
        "latest_version": info.application_version,
        "release_id": info.release_id,
        "build_id": info.build_id,
        "release_path": "EOAT-Atlas.zip",
        "minimum_supported_version": "0.1.0",
        "sha256": "0" * 64,
        "package_size": 1,
        "published_at": "2026-07-15T00:00:00Z",
    }
    assert validate_manifest(manifest)["build_id"] == info.build_id


def test_actual_launcher_compares_application_release_not_launcher_version(tmp_path: Path) -> None:
    manifest_path = tmp_path / "latest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "latest_version": "0.10.0",
                "release_id": "eoat-atlas-0.10.0",
                "build_id": "eoat-atlas-0.10.0-abcdef0-20260715T120000Z",
                "minimum_supported_version": "0.9.0",
            }
        ),
        encoding="utf-8",
    )
    checker = UpdateChecker(LauncherConfig(updateManifestPath=str(manifest_path)))
    result = checker.check(
        LauncherVersionInfo(version="0.9.9", releaseId="eoat-atlas-0.9.9", buildId="old-build")
    )
    assert result.status == "update_available"
    assert result.availableReleaseId == "eoat-atlas-0.10.0"
    assert result.availableBuildId.endswith("20260715T120000Z")
    assert checker.check(LauncherVersionInfo(version="1.0.0")).status == "newer_local"


def test_release_id_is_stable_per_version_and_build_ids_distinguish_builds() -> None:
    version = Version.parse("3.4.5")
    first = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)
    second = first + timedelta(seconds=1)
    assert f"eoat-atlas-{version}" == "eoat-atlas-3.4.5"
    assert build_identifier(version, "abcdef012345", first) != build_identifier(version, "abcdef012345", second)


def test_publish_metadata_consumes_source_version_without_mutating_canonical() -> None:
    root = Path(__file__).resolve().parents[1]
    path = root / "app/atlas/version.json"
    before = path.read_bytes()
    source = _read_source_metadata()
    target = _target_metadata(source, Version.parse(source["app_version"]))
    assert target["app_version"] == source["app_version"]
    assert target["release_id"] == f"eoat-atlas-{source['app_version']}"
    assert target["source_git_commit"] == target["git_commit"]
    assert path.read_bytes() == before
