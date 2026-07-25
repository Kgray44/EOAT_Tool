"""Focused contract tests for the root-owned coordinated release helper."""
from __future__ import annotations

import importlib.util
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PRIVILEGED = ROOT / "deployment" / "privileged"
sys.path.insert(0, str(PRIVILEGED))
SPEC = importlib.util.spec_from_file_location(
    "coordinated_release_retry_test",
    PRIVILEGED / "coordinated_release_retry.py",
)
assert SPEC and SPEC.loader
coordinator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(coordinator)


def test_policy_requires_explicit_pre_activation_targets(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    helper = tmp_path / "helper.py"
    helper.write_text("helper", encoding="utf-8")
    policy = tmp_path / "policy.json"
    policy.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(coordinator.web, "require_root_owned", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(coordinator.web, "require_root_chain", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(coordinator.web, "sha256", lambda path: "digest")
    monkeypatch.setattr(coordinator, "__file__", str(helper))
    with pytest.raises(coordinator.web.InstallError, match="policy or helper"):
        coordinator.policy(policy)


def test_shared_http_acceptance_is_bound_to_the_just_activated_server_release(tmp_path: Path) -> None:
    server = tmp_path / "eoat-atlas-server-0.22.6"
    server.mkdir()
    source = {"schema": "20260721_0008", "application_version": "0.22.6"}
    bound = coordinator.acceptance_policy(source, server)
    assert bound["api_release"] == str(server.resolve())
    assert "api_release" not in source


def test_extract_failure_removes_only_temporary_api_staging(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    archive = tmp_path / "server.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("unexpected.txt", "not a release")
    manifest = tmp_path / "manifest.json"
    manifest.write_text('{"archive_sha256":"approved"}', encoding="utf-8")
    releases = tmp_path / "releases"
    releases.mkdir()
    transaction = tmp_path / "transaction"
    transaction.mkdir()
    monkeypatch.setattr(coordinator, "API_RELEASES", releases)
    monkeypatch.setattr(coordinator.web, "sha256", lambda _path: "approved")
    policy = {
        "server_archive_path": str(archive),
        "server_archive_sha256": "approved",
        "server_manifest_path": str(manifest),
        "server_manifest_sha256": "approved",
        "server_release_id": "release",
    }
    with pytest.raises(coordinator.web.InstallError, match="metadata"):
        coordinator.extract_server(policy, transaction)
    assert not list(releases.glob(".staging-*"))
    assert not (releases / "release").exists()
