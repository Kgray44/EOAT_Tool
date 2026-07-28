"""Focused contract tests for the root-owned coordinated release helper."""
from __future__ import annotations

import importlib.util
import json
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


def test_post_activation_rollback_restores_receipt_targets_and_is_idempotent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    control = tmp_path / "control"
    api_releases = tmp_path / "api" / "releases"
    web_releases = tmp_path / "web" / "releases"
    old_api, new_api = api_releases / "old", api_releases / "new"
    old_web, new_web = web_releases / "old", web_releases / "new"
    for path in (old_api, new_api, old_web, new_web):
        path.mkdir(parents=True)
    api_current, web_current = tmp_path / "api-current", tmp_path / "web-current"
    try:
        api_current.symlink_to(new_api, target_is_directory=True)
        web_current.symlink_to(new_web, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks require Linux/root or Windows developer mode")
    transaction = control / "transactions" / "coordinated-20260728T001346Z-f99297d1"
    transaction.mkdir(parents=True)
    transaction.joinpath("receipt.json").write_text(json.dumps({
        "receipt_schema_version": 2, "helper_version": "1.2.0", "state": "active",
        "activation_complete": True, "old_api": str(old_api), "old_web": str(old_web),
        "new_api": str(new_api), "new_web": str(new_web), "schema": "20260721_0008",
        "service": "eoat-atlas.service", "writes_enabled": False,
    }), encoding="utf-8")
    monkeypatch.setattr(coordinator, "CONTROL_ROOT", control)
    monkeypatch.setattr(coordinator, "API_RELEASES", api_releases)
    monkeypatch.setattr(coordinator, "WEB_RELEASES", web_releases)
    monkeypatch.setattr(coordinator, "API_CURRENT", api_current)
    monkeypatch.setattr(coordinator, "WEB_CURRENT", web_current)
    monkeypatch.setattr(coordinator.web, "require_root_chain", lambda *_: None)
    monkeypatch.setattr(coordinator.web, "require_root_tree", lambda *_: None)
    monkeypatch.setattr(coordinator.web, "require_root_owned", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(coordinator.web, "nginx_test_reload", lambda: None)
    monkeypatch.setattr(coordinator.web, "wait_api", lambda *_: None)
    monkeypatch.setattr(coordinator.web, "request_check", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(coordinator.web, "api_health", lambda *_: {"writes_enabled": False})
    monkeypatch.setattr(coordinator.subprocess, "run", lambda *_args, **_kwargs: None)
    result = coordinator.post_activation_rollback(transaction.name)
    assert result == {"transaction": transaction.name, "state": "rolled_back", "idempotent": False}
    assert api_current.resolve() == old_api.resolve()
    assert web_current.resolve() == old_web.resolve()
    receipt = json.loads(transaction.joinpath("post-activation-rollback.json").read_text(encoding="utf-8"))
    assert receipt["rollback_frontend_generation"] == "old"
    assert coordinator.post_activation_rollback(transaction.name)["idempotent"] is True


@pytest.mark.parametrize("identifier", ["../receipt", "coordinated-20260728T001346Z-f99297d1/../x"])
def test_post_activation_rollback_rejects_traversal(identifier: str) -> None:
    with pytest.raises(coordinator.web.InstallError, match="identifier is invalid"):
        coordinator.post_activation_rollback(identifier)


def test_coordinated_sudoers_exposes_only_fixed_governed_operations() -> None:
    source = (PRIVILEGED / "eoat-atlas-coordinated.sudoers").read_text(encoding="utf-8")
    assert "preflight --policy /etc/eoat-atlas/coordinated-release-policy.json" in source
    assert "activate --policy /etc/eoat-atlas/coordinated-release-policy.json" in source
    assert "post-activation-rollback --transaction *" in source
    rules = "\n".join(line for line in source.splitlines() if not line.startswith("#"))
    assert "systemctl" not in rules and "nginx" not in rules and "/bin/sh" not in rules
    assert "ALL=(ALL)" not in rules
