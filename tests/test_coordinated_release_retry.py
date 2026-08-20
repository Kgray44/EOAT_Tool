"""Focused contract tests for the root-owned coordinated release helper."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import stat
import sys
import zipfile
from pathlib import Path

import pytest

from deployment.http_web_bundle import create_bundle

ROOT = Path(__file__).resolve().parents[1]
PRIVILEGED = ROOT / "deployment" / "privileged"
sys.path.insert(0, str(PRIVILEGED))
SPEC = importlib.util.spec_from_file_location(
    "coordinated_release_retry_test",
    PRIVILEGED / "coordinated_release_retry.py",
)
assert SPEC and SPEC.loader
coordinator = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = coordinator
SPEC.loader.exec_module(coordinator)


def sealing_policy(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[dict[str, object], Path]:
    """Create real upload files and a real static bundle for sealing tests."""
    upload = tmp_path / "incoming"
    upload.mkdir()
    archive = upload / "server.zip"
    archive.write_bytes(b"immutable-server-archive")
    manifest = upload / "server.manifest.json"
    manifest.write_text('{"archive_sha256":"fixture"}', encoding="utf-8")
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "assets" / "app.js").write_text("console.log('EOAT');", encoding="utf-8")
    (static / "index.html").write_text("<title>EOAT</title><script src='/assets/app.js'></script>", encoding="utf-8")
    bundle = upload / "bundle"
    bundle_sha = create_bundle(
        static,
        ROOT / "deployment" / "runtime" / "nginx" / "eoat-atlas-http-web.conf.template",
        bundle,
        release_id="web-0.23.6-test",
        app_version="0.23.6",
        source_commit="a" * 40,
        compatible_api_version="1.4.0",
        compatible_schema="20260721_0008",
    )["bundle_sha256"]
    sealed = tmp_path / "sealed-artifacts"
    sealed.mkdir()
    monkeypatch.setattr(coordinator, "UPLOAD_ROOT", upload)
    monkeypatch.setattr(coordinator, "SEALED_ROOT", sealed)
    monkeypatch.setattr(coordinator.web, "require_root_owned", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(coordinator.web, "require_root_chain", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(coordinator.web, "require_root_tree", lambda *_args, **_kwargs: None)
    return {
        "server_archive_path": str(archive),
        "server_archive_sha256": coordinator.web.sha256(archive),
        "server_manifest_path": str(manifest),
        "server_manifest_sha256": coordinator.web.sha256(manifest),
        "server_release_id": "sealed-0.23.6-fixture",
        "web_release_id": "web-0.23.6-test",
        "bundle_path": str(bundle),
        "bundle_sha256": bundle_sha,
        "application_version": "0.23.6",
        "source_commit": "a" * 40,
        "schema": "20260721_0008",
        "canonical_migration_sha256": "b" * 64,
        "expected_active_api": str(tmp_path / "api-current-target"),
        "expected_active_web": str(tmp_path / "web-current-target"),
        "helper_sha256": "fixture",
        "web_helper_sha256": "fixture",
    }, sealed


def test_sealing_receipt_uses_final_relative_paths_and_reopens_safely(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    value, sealed_root = sealing_policy(monkeypatch, tmp_path)
    sealed = coordinator.seal_artifacts(value)
    assert sealed.root == sealed_root / value["server_release_id"]
    assert sealed.server_archive.is_file() and sealed.server_manifest.is_file() and sealed.bundle.is_dir()
    assert sealed.receipt_path == sealed.root / "sealing-receipt.json"
    receipt = json.loads(sealed.receipt_path.read_text(encoding="utf-8"))
    assert receipt["schema"] == 2
    assert ".sealing-" not in json.dumps(receipt, sort_keys=True)
    assert receipt["sealed_bundle"] == "bundle"
    for record in receipt["files"]:
        member = sealed.root / record["sealed"]
        assert member.is_file() and member.stat().st_size == record["size"]
        assert coordinator.web.sha256(member) == record["sha256"]
        assert member.is_relative_to(sealed.root)
    Path(str(value["server_archive_path"])).write_bytes(b"untrusted upload changed after sealing")
    returned = coordinator.sealed_policy(value)
    assert all(".sealing-" not in str(item) for item in returned.values())
    assert Path(returned["server_archive_path"]).is_file()
    assert coordinator.seal_artifacts(value) == sealed


def test_sealed_receipt_rejects_obsolete_temporary_paths_without_rewriting_evidence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    value, _ = sealing_policy(monkeypatch, tmp_path)
    sealed = coordinator.seal_artifacts(value)
    stale = json.loads(sealed.receipt_path.read_text(encoding="utf-8"))
    stale.update({"schema": 1, "sealed_bundle": "/root/.sealing-deadbeef/bundle"})
    original = json.dumps(stale, sort_keys=True, indent=2) + "\n"
    sealed.receipt_path.write_text(original, encoding="utf-8")
    with pytest.raises(coordinator.web.InstallError, match="obsolete temporary-path schema"):
        coordinator.seal_artifacts(value)
    assert sealed.receipt_path.read_text(encoding="utf-8") == original


@pytest.mark.parametrize("field, member", [("server_archive", "../outside"), ("server_manifest", "/tmp/outside")])
def test_sealed_receipt_rejects_traversal_and_absolute_members(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, field: str, member: str
) -> None:
    value, _ = sealing_policy(monkeypatch, tmp_path)
    sealed = coordinator.seal_artifacts(value)
    receipt = json.loads(sealed.receipt_path.read_text(encoding="utf-8"))
    receipt[field] = member
    sealed.receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(coordinator.web.InstallError, match="relative non-traversing"):
        coordinator.seal_artifacts(value)


def test_sealed_receipt_detects_changed_or_missing_sealed_members(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    value, _ = sealing_policy(monkeypatch, tmp_path)
    sealed = coordinator.seal_artifacts(value)
    sealed.server_archive.write_bytes(b"changed")
    with pytest.raises(coordinator.web.InstallError, match="recorded hash or size"):
        coordinator.seal_artifacts(value)


def test_sealed_receipt_rejects_policy_hash_mismatch_and_symlink_members(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    value, _ = sealing_policy(monkeypatch, tmp_path)
    sealed = coordinator.seal_artifacts(value)
    receipt = json.loads(sealed.receipt_path.read_text(encoding="utf-8"))
    receipt["policy_semantic_sha256"] = "0" * 64
    sealed.receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(coordinator.web.InstallError, match="approved policy or coordinator"):
        coordinator.seal_artifacts(value)
    receipt["policy_semantic_sha256"] = coordinator._policy_digest(value)
    sealed.receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    target = sealed.root / "real-server.zip"
    sealed.server_archive.rename(target)
    try:
        sealed.server_archive.symlink_to(target.name)
    except OSError:
        pytest.skip("symlink creation is unavailable on this test host")
    with pytest.raises(coordinator.web.InstallError, match="missing or unsafe"):
        coordinator.seal_artifacts(value)


def test_preflight_seals_then_uses_only_final_paths_without_changing_active_pointers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    value, _ = sealing_policy(monkeypatch, tmp_path)
    api, web = tmp_path / "api-current-target", tmp_path / "web-current-target"
    api.mkdir()
    web.mkdir()
    api_current, web_current = tmp_path / "api-current", tmp_path / "web-current"
    api_current.mkdir()
    web_current.mkdir()
    value["expected_active_api"] = str(api_current)
    value["expected_active_web"] = str(web_current)
    monkeypatch.setattr(coordinator, "API_CURRENT", api_current)
    monkeypatch.setattr(coordinator, "WEB_CURRENT", web_current)
    monkeypatch.setattr(coordinator.web, "api_health", lambda *_: {"writes_enabled": False})
    monkeypatch.setattr(coordinator.web, "api_loopback_only", lambda: True)
    monkeypatch.setattr(coordinator.web, "mysql_loopback_only", lambda: True)
    monkeypatch.setattr(coordinator.web, "listener_policy", lambda _value: True)
    monkeypatch.setattr(coordinator.web, "nginx_worker_user", lambda: "www-data")
    monkeypatch.setattr(
        coordinator.subprocess, "run", lambda *_args, **_kwargs: type("Result", (), {"returncode": 0})()
    )
    before = (api_current.resolve(), web_current.resolve())
    sealed_policy = coordinator.sealed_policy(value)
    result = coordinator.preflight(sealed_policy)
    assert result["helper_version"] == coordinator.HELPER_VERSION
    assert (api_current.resolve(), web_current.resolve()) == before
    sealed = coordinator.sealed_policy(value)
    assert Path(sealed["server_archive_path"]).is_relative_to(coordinator.SEALED_ROOT)
    assert Path(sealed["bundle_path"]).is_relative_to(coordinator.SEALED_ROOT)


def test_preflight_rejects_unsealed_artifacts_without_mutating_active_pointers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    value, _ = sealing_policy(monkeypatch, tmp_path)
    api, web = tmp_path / "api-current", tmp_path / "web-current"
    api.mkdir()
    web.mkdir()
    value["expected_active_api"] = str(api)
    value["expected_active_web"] = str(web)
    monkeypatch.setattr(coordinator, "API_CURRENT", api)
    monkeypatch.setattr(coordinator, "WEB_CURRENT", web)
    with pytest.raises(coordinator.web.InstallError, match="already-sealed"):
        coordinator.preflight(value)
    assert not list(coordinator.SEALED_ROOT.iterdir())


def test_listener_policy_requires_an_explicit_approved_tls_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(coordinator.web, "no_tls_listener", lambda: True)
    monkeypatch.setattr(coordinator.web, "approved_existing_self_signed_tls_listener", lambda: True)
    assert coordinator.web.listener_policy({"tls_listener_policy": "http_only"})
    assert coordinator.web.listener_policy({"tls_listener_policy": "approved_self_signed_existing"})
    assert not coordinator.web.listener_policy({"tls_listener_policy": "unexpected"})


def test_approved_tls_exception_uses_only_the_pinned_loopback_https_listener() -> None:
    assert coordinator.web.acceptance_base_url({"tls_listener_policy": "http_only"}) == "http://eoat-atlas.gwplastics.com"
    assert (
        coordinator.web.acceptance_base_url({"tls_listener_policy": "approved_self_signed_existing"})
        == "https://eoat-atlas.gwplastics.com:8443"
    )


def test_approved_tls_listener_requires_each_nginx_declaration_as_a_substring(monkeypatch: pytest.MonkeyPatch) -> None:
    responses = iter(
        [
            type("Result", (), {"stdout": 'LISTEN 0 511 0.0.0.0:443 0.0.0.0:* users:(("nginx",pid=1))\n', "returncode": 0})(),
            type("Result", (), {"stdout": "listen 443 ssl;\nlisten 8443 ssl;\nssl_certificate /etc/ssl/certs/eoat-atlas-test.crt;\nssl_certificate_key /etc/ssl/private/eoat-atlas-test.key;", "returncode": 0})(),
            type("Result", (), {"stdout": "subject=CN=eoat\nissuer=CN=eoat\n", "returncode": 0})(),
        ]
    )
    monkeypatch.setattr(coordinator.web.subprocess, "run", lambda *_args, **_kwargs: next(responses))
    assert coordinator.web.approved_existing_self_signed_tls_listener()


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


def test_wait_target_uses_immutable_api_metadata_when_legacy_health_fields_are_absent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    release = tmp_path / "eoat-atlas-server-0.26.11"
    release.mkdir()
    monkeypatch.setattr(coordinator, "API_CURRENT", release)
    monkeypatch.setattr(coordinator.web, "api_health", lambda _value: {"compatible": True})
    monkeypatch.setattr(
        coordinator,
        "_api_release_attestation",
        lambda *_args: (
            release,
            {
                "application_version": "0.26.11",
                "schema": "20260820_0013",
                "source_commit": "a" * 40,
            },
        ),
    )
    coordinator.wait_target(
        {"application_version": "0.26.11", "schema": "20260820_0013", "source_commit": "a" * 40}
    )


def test_wait_target_rejects_mismatched_immutable_api_metadata(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    release = tmp_path / "eoat-atlas-server-0.26.11"
    release.mkdir()
    monkeypatch.setattr(coordinator, "API_CURRENT", release)
    monkeypatch.setattr(coordinator.web, "api_health", lambda _value: {"compatible": True})
    monkeypatch.setattr(
        coordinator,
        "_api_release_attestation",
        lambda *_args: (
            release,
            {
                "application_version": "0.26.11",
                "schema": "20260820_0013",
                "source_commit": "b" * 40,
            },
        ),
    )
    with pytest.raises(coordinator.web.InstallError, match="metadata does not match"):
        coordinator.wait_target(
            {"application_version": "0.26.11", "schema": "20260820_0013", "source_commit": "a" * 40}
        )


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


@pytest.mark.skipif(os.name == "nt", reason="atomic replacement of directory symlinks is Linux-only")
def test_post_activation_rollback_restores_receipt_targets_and_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    control = tmp_path / "control"
    api_releases = tmp_path / "api" / "releases"
    web_releases = tmp_path / "web" / "releases"
    old_api = api_releases / "eoat-atlas-server-0.22.12-old"
    new_api = api_releases / "eoat-atlas-server-0.24.0-new"
    old_web, new_web = web_releases / "old", web_releases / "new"
    for path in (old_web, new_web):
        path.mkdir(parents=True)
    venv_source = api_releases / "eoat-atlas-server-0.22.12-venv-source" / "venv"
    venv_source.mkdir(parents=True)
    for path, version, commit in (
        (old_api, "0.22.12", "a" * 40),
        (new_api, "0.24.0", "b" * 40),
    ):
        path.mkdir(parents=True)
        path.joinpath("release_metadata.json").write_text(
            json.dumps(
                {
                    "app_version": version,
                    "release_id": f"eoat-atlas-{version}",
                    "source_git_commit": commit,
                    "database_schema_revision": "20260721_0008",
                }
            ),
            encoding="utf-8",
        )
        path.joinpath("venv").symlink_to(venv_source, target_is_directory=True)
    api_current, web_current = tmp_path / "api-current", tmp_path / "web-current"
    try:
        api_current.symlink_to(new_api, target_is_directory=True)
        web_current.symlink_to(new_web, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks require Linux/root or Windows developer mode")
    transaction = control / "transactions" / "coordinated-20260728T001346Z-f99297d1"
    transaction.mkdir(parents=True)
    monkeypatch.setattr(coordinator, "API_RELEASES", api_releases)
    monkeypatch.setattr(coordinator, "WEB_RELEASES", web_releases)
    monkeypatch.setattr(coordinator.web, "require_root_chain", lambda *_: None)
    monkeypatch.setattr(coordinator.web, "require_root_tree", lambda *_: None)
    monkeypatch.setattr(coordinator.web, "require_root_owned", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(coordinator, "_service_identity", lambda: (os.getuid(), os.getgid()))
    monkeypatch.setattr(coordinator, "_api_release_parent_chain", lambda *_args: None)
    old_api_attestation = coordinator._api_release_attestation(old_api, "old_api")[1]
    old_web_attestation = coordinator._web_release_attestation(old_web, "old_web")[1]
    transaction.joinpath("receipt.json").write_text(
        json.dumps(
            {
                "receipt_schema_version": 3,
                "helper_version": "1.3.2",
                "state": "active",
                "activation_complete": True,
                "old_api": str(old_api),
                "old_web": str(old_web),
                "new_api": str(new_api),
                "new_web": str(new_web),
                "schema": "20260721_0008",
                "service": "eoat-atlas.service",
                "writes_enabled": False,
                "old_api_attestation": old_api_attestation,
                "old_web_attestation": old_web_attestation,
                "active_pointer_identities": {
                    "api": {"path": str(api_current), "target": str(old_api)},
                    "web": {"path": str(web_current), "target": str(old_web)},
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(coordinator, "CONTROL_ROOT", control)
    monkeypatch.setattr(coordinator, "API_CURRENT", api_current)
    monkeypatch.setattr(coordinator, "WEB_CURRENT", web_current)
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


@pytest.mark.skipif(os.name == "nt", reason="service-owned rollback validation is Linux-only")
def test_legacy_transaction_receipt_requires_preserved_fallback_evidence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    transaction = tmp_path / "control" / "transactions" / "coordinated-20260728T001346Z-f99297d1"
    transaction.mkdir(parents=True)
    receipt = transaction / "receipt.json"
    original = {"receipt_schema_version": 2, "state": "active"}
    receipt.write_text(json.dumps(original), encoding="utf-8")
    monkeypatch.setattr(coordinator, "CONTROL_ROOT", tmp_path / "control")
    monkeypatch.setattr(coordinator.web, "require_root_chain", lambda *_: None)
    monkeypatch.setattr(coordinator.web, "require_root_owned", lambda *_args, **_kwargs: None)
    with pytest.raises(coordinator.web.InstallError, match="lacks rollback attestations"):
        coordinator._transaction_receipt(transaction.name)
    assert json.loads(receipt.read_text(encoding="utf-8")) == original


@pytest.mark.skipif(os.name == "nt", reason="service-owned rollback validation is Linux-only")
def test_service_owned_api_release_attestation_rejects_drift_and_unsafe_members(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    releases = tmp_path / "opt" / "eoat-atlas" / "releases"
    release = releases / "eoat-atlas-server-0.22.12-accepted"
    venv = releases / "eoat-atlas-server-0.22.12-venv-source" / "venv"
    venv.mkdir(parents=True)
    release.mkdir(parents=True)
    metadata = release / "release_metadata.json"
    metadata.write_text(
        json.dumps(
            {
                "app_version": "0.22.12",
                "release_id": "eoat-atlas-0.22.12",
                "source_git_commit": "a" * 40,
                "database_schema_revision": "20260721_0008",
            }
        ),
        encoding="utf-8",
    )
    release.joinpath("venv").symlink_to(venv, target_is_directory=True)
    monkeypatch.setattr(coordinator, "API_RELEASES", releases)
    monkeypatch.setattr(coordinator, "_service_identity", lambda: (os.getuid(), os.getgid()))
    monkeypatch.setattr(coordinator, "_api_release_parent_chain", lambda *_args: None)
    _, attestation = coordinator._api_release_attestation(release, "old_api")
    metadata.write_text(metadata.read_text(encoding="utf-8").replace("a" * 40, "b" * 40), encoding="utf-8")
    _, changed = coordinator._api_release_attestation(release, "old_api")
    with pytest.raises(coordinator.web.InstallError, match="activation attestation"):
        coordinator._require_attestation(changed, attestation, "old_api")
    metadata.write_text(metadata.read_text(encoding="utf-8").replace("b" * 40, "a" * 40), encoding="utf-8")
    release.joinpath("unsafe").symlink_to(venv, target_is_directory=True)
    with pytest.raises(coordinator.web.InstallError, match="unsafe API release symlink"):
        coordinator._api_release_attestation(release, "old_api")


@pytest.mark.skipif(os.name == "nt", reason="embedded virtualenv validation is Linux-only")
def test_service_owned_api_release_attestation_accepts_only_versioned_system_python_in_embedded_venv(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    releases = tmp_path / "opt" / "eoat-atlas" / "releases"
    release = releases / "eoat-atlas-server-0.26.10-legacy"
    venv_bin = release / "venv" / "bin"
    venv_bin.mkdir(parents=True)
    release.joinpath("release_metadata.json").write_text(
        json.dumps(
            {
                "app_version": "0.26.10",
                "release_id": "eoat-atlas-0.26.10",
                "source_git_commit": "a" * 40,
                "database_schema_revision": "20260729_0009",
            }
        ),
        encoding="utf-8",
    )
    venv_bin.joinpath("python3").symlink_to("/usr/bin/python3")
    monkeypatch.setattr(coordinator, "API_RELEASES", releases)
    monkeypatch.setattr(coordinator, "_service_identity", lambda: (os.getuid(), os.getgid()))
    monkeypatch.setattr(coordinator, "_api_release_parent_chain", lambda *_args: None)
    coordinator._api_release_attestation(release, "old_api")
    venv_bin.joinpath("python3").unlink()
    venv_bin.joinpath("python3").symlink_to("/usr/bin/env")
    with pytest.raises(coordinator.web.InstallError, match="unsafe API release symlink"):
        coordinator._api_release_attestation(release, "old_api")


@pytest.mark.parametrize("identifier", ["../receipt", "coordinated-20260728T001346Z-f99297d1/../x"])
def test_post_activation_rollback_rejects_traversal(identifier: str) -> None:
    with pytest.raises(coordinator.web.InstallError, match="identifier is invalid"):
        coordinator.post_activation_rollback(identifier)


def legacy_reconciliation_fixture(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Path, Path, Path, bytes]:
    """Create an already-restored schema-2 transaction without host mutation."""
    control = tmp_path / "control"
    api_releases = tmp_path / "api" / "releases"
    web_releases = tmp_path / "web" / "releases"
    old_api, new_api = api_releases / "old-api", api_releases / "new-api"
    old_web, new_web = web_releases / "old-web", web_releases / "new-web"
    for path in (old_api, new_api, old_web, new_web):
        path.mkdir(parents=True)
    api_current, web_current = tmp_path / "api-current", tmp_path / "web-current"
    try:
        api_current.symlink_to(old_api, target_is_directory=True)
        web_current.symlink_to(old_web, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks require Linux/root or Windows developer mode")
    transaction = control / "transactions" / "coordinated-20260728T160353Z-ff94e232"
    transaction.mkdir(parents=True)
    source = {
        "receipt_schema_version": 2,
        "helper_version": "1.3.1",
        "state": "active",
        "activation_complete": True,
        "old_api": str(old_api),
        "old_web": str(old_web),
        "new_api": str(new_api),
        "new_web": str(new_web),
        "schema": "20260721_0008",
        "service": "eoat-atlas.service",
        "writes_enabled": False,
    }
    receipt = transaction / "receipt.json"
    receipt.write_text(json.dumps(source, sort_keys=True), encoding="utf-8")
    monkeypatch.setattr(coordinator, "CONTROL_ROOT", control)
    monkeypatch.setattr(coordinator, "API_RELEASES", api_releases)
    monkeypatch.setattr(coordinator, "WEB_RELEASES", web_releases)
    monkeypatch.setattr(coordinator, "API_CURRENT", api_current)
    monkeypatch.setattr(coordinator, "WEB_CURRENT", web_current)
    monkeypatch.setattr(coordinator.web, "require_root_chain", lambda *_: None)
    monkeypatch.setattr(coordinator.web, "require_root_owned", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(coordinator.web, "require_root_tree", lambda *_: None)
    monkeypatch.setattr(coordinator, "_service_identity", lambda: (0, 0))
    monkeypatch.setattr(coordinator, "_api_release_parent_chain", lambda *_: None)
    monkeypatch.setattr(coordinator, "_safe_mode", lambda *_args, **_kwargs: None)
    def runtime_evidence(_transaction: Path, value: dict[str, object]) -> dict[str, object]:
        active_api, active_web = coordinator._require_legacy_current_targets(value)
        return {
            "rollback_api": str(active_api),
            "rollback_web": str(active_web),
            "active_pointer_identities": {
                "api": {"path": str(api_current), "target": str(active_api)},
                "web": {"path": str(web_current), "target": str(active_web)},
            },
            "api_attestation": {"path": str(active_api), "tree_sha256": "a" * 64},
            "web_attestation": {"path": str(active_web), "tree_sha256": "b" * 64},
            "application_version": "0.22.12",
            "schema": "20260721_0008",
            "writes_enabled": False,
            "api_health": {"application_version": "0.22.12", "release_id": "eoat-atlas-0.22.12", "writes_enabled": False},
            "nginx_validation": "passed",
            "service_states": {"eoat-atlas.service": "active", "nginx.service": "active"},
            "data_state": {"schema": "eoat_atlas_prod", "count": 1},
        }

    monkeypatch.setattr(coordinator, "_legacy_runtime_evidence", runtime_evidence)
    return transaction, api_current, web_current, receipt.read_bytes()


def test_reconcile_legacy_rollback_records_only_already_active_targets(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    transaction, api_current, web_current, original = legacy_reconciliation_fixture(monkeypatch, tmp_path)
    # Historical non-coordinator deployment evidence is not in this helper's
    # state machine and must not be interpreted as a newer transaction.
    transaction.parent.joinpath("deploy-0.22.5-20260725T141312Z").mkdir()
    calls: list[object] = []
    monkeypatch.setattr(coordinator.subprocess, "run", lambda *args, **kwargs: calls.append(args) or None)
    result = coordinator.reconcile_legacy_rollback(transaction.name)
    assert result == {"transaction": transaction.name, "state": "rolled_back", "idempotent": False}
    assert transaction.joinpath("receipt.json").read_bytes() == original
    assert api_current.resolve() == Path(json.loads(original)["old_api"])
    assert web_current.resolve() == Path(json.loads(original)["old_web"])
    assert not calls
    evidence = json.loads(transaction.joinpath("post-activation-rollback.json").read_text(encoding="utf-8"))
    assert evidence["reconciliation_mode"] == "legacy_already_rolled_back"
    assert evidence["pointer_mutation_performed"] is False
    assert evidence["service_restart_performed"] is False
    assert evidence["nginx_reload_performed"] is False
    assert evidence["api_attestation"]["tree_sha256"] == "a" * 64
    assert coordinator.reconcile_legacy_rollback(transaction.name)["idempotent"] is True


def test_reconcile_legacy_rollback_rejects_pointer_mismatch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    transaction, api_current, _web_current, _ = legacy_reconciliation_fixture(monkeypatch, tmp_path)
    mismatch = Path(json.loads(transaction.joinpath("receipt.json").read_text(encoding="utf-8"))["new_api"])
    api_current.unlink()
    api_current.symlink_to(mismatch, target_is_directory=True)
    with pytest.raises(coordinator.web.InstallError, match="not already physically rolled back"):
        coordinator.reconcile_legacy_rollback(transaction.name)
    assert not transaction.joinpath("post-activation-rollback.json").exists()


def test_reconcile_legacy_rollback_rejects_schema_and_conflicting_receipt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    transaction, _api_current, _web_current, _ = legacy_reconciliation_fixture(monkeypatch, tmp_path)
    source = json.loads(transaction.joinpath("receipt.json").read_text(encoding="utf-8"))
    source["receipt_schema_version"] = 3
    transaction.joinpath("receipt.json").write_text(json.dumps(source), encoding="utf-8")
    with pytest.raises(coordinator.web.InstallError, match="only transaction receipt schema 2"):
        coordinator.reconcile_legacy_rollback(transaction.name)
    source["receipt_schema_version"] = 2
    transaction.joinpath("receipt.json").write_text(json.dumps(source), encoding="utf-8")
    transaction.joinpath("post-activation-rollback.json").write_text('{"state":"bad"}', encoding="utf-8")
    with pytest.raises(coordinator.web.InstallError, match="ownership or mode|conflicts"):
        coordinator.reconcile_legacy_rollback(transaction.name)


def test_api_release_parent_policy_accepts_root_service_group_but_not_writable() -> None:
    root_service_group = os.stat_result((stat.S_IFDIR | 0o750, 0, 0, 0, 0, 42, 0, 0, 0, 0))
    writable = os.stat_result((stat.S_IFDIR | 0o770, 0, 0, 0, 0, 42, 0, 0, 0, 0))
    wrong_owner = os.stat_result((stat.S_IFDIR | 0o750, 0, 0, 0, 1, 42, 0, 0, 0, 0))
    assert coordinator._api_release_parent_is_safe(root_service_group, 42)
    assert not coordinator._api_release_parent_is_safe(writable, 42)
    assert not coordinator._api_release_parent_is_safe(wrong_owner, 42)


def test_helper_version_is_safe_without_root_execution(capsys: pytest.CaptureFixture[str]) -> None:
    assert coordinator.main(["--version"]) == 0
    assert json.loads(capsys.readouterr().out) == {"helper_version": coordinator.HELPER_VERSION}


def test_coordinated_sudoers_exposes_only_fixed_governed_operations() -> None:
    source = (PRIVILEGED / "eoat-atlas-coordinated.sudoers").read_text(encoding="utf-8")
    assert "preflight --policy /etc/eoat-atlas/coordinated-release-policy.json" in source
    assert "activate --policy /etc/eoat-atlas/coordinated-release-policy.json" in source
    assert "post-activation-rollback --transaction *" in source
    assert "reconcile-legacy-rollback --transaction *" in source
    rules = "\n".join(line for line in source.splitlines() if not line.startswith("#"))
    assert "systemctl" not in rules and "nginx" not in rules and "/bin/sh" not in rules
    assert "ALL=(ALL)" not in rules


def test_upload_zone_rejects_traversal_and_wrong_roots(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    upload = tmp_path / "incoming"
    upload.mkdir()
    artifact = upload / "candidate.zip"
    artifact.write_bytes(b"candidate")
    monkeypatch.setattr(coordinator, "UPLOAD_ROOT", upload)
    assert coordinator._upload_member(artifact) == artifact
    with pytest.raises(coordinator.web.InstallError, match="approved upload root"):
        coordinator._upload_member(tmp_path / "outside.zip")
    with pytest.raises(coordinator.web.InstallError, match="expected non-symlink"):
        coordinator._upload_member(upload / "missing.zip")


def test_policy_reports_a_bom_as_a_governed_diagnostic(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    policy = tmp_path / "policy.json"
    policy.write_bytes(b"\xef\xbb\xbf{}")
    helper = tmp_path / "helper.py"
    helper.write_text("helper", encoding="utf-8")
    monkeypatch.setattr(coordinator, "__file__", str(helper))
    monkeypatch.setattr(coordinator.web, "require_root_owned", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(coordinator.web, "require_root_chain", lambda *_args, **_kwargs: None)
    with pytest.raises(coordinator.web.InstallError, match="without a BOM"):
        coordinator.policy(policy)


def test_migration_plan_accepts_a_hash_bound_ordered_multi_revision_traversal() -> None:
    value: dict[str, object] = {
        "schema": "20260820_0013",
        "migration_plan": {
            "current_schema": "20260729_0009",
            "target_schema": "20260820_0013",
            "revisions": [
                {"revision": "20260811_0005", "sha256": "a" * 64},
                {"revision": "20260813_0010", "sha256": "b" * 64},
                {"revision": "20260820_0013", "sha256": "c" * 64},
            ],
        },
    }
    current, target, revisions = coordinator.migration_plan(value)
    assert (current, target) == ("20260729_0009", "20260820_0013")
    assert [item["revision"] for item in revisions] == ["20260811_0005", "20260813_0010", "20260820_0013"]


@pytest.mark.parametrize(
    "plan, message",
    [
        ({"current_schema": "20260729_0009", "target_schema": "20260820_0013", "revisions": []}, "does not deterministically"),
        ({"current_schema": "20260729_0009", "target_schema": "20260820_0013", "revisions": [{"revision": "20260820_0013", "sha256": "x" * 64}]}, "identity is invalid"),
        ({"current_schema": "20260820_0013", "target_schema": "20260820_0013", "revisions": [{"revision": "20260820_0013", "sha256": "a" * 64}]}, "zero-migration"),
    ],
)
def test_migration_plan_rejects_incomplete_or_mismatched_traversals(plan: dict[str, object], message: str) -> None:
    with pytest.raises(coordinator.web.InstallError, match=message):
        coordinator.migration_plan({"schema": "20260820_0013", "migration_plan": plan})


def test_migration_archive_requires_each_approved_revision_once_and_untampered(tmp_path: Path) -> None:
    archive = tmp_path / "server.zip"
    payload = b"revision = '20260820_0013'\n"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("server/migrations/versions/20260820_0013_merge.py", payload)
    approved = ({"revision": "20260820_0013", "sha256": hashlib.sha256(payload).hexdigest()},)
    coordinator.validate_migration_archive(archive, approved)
    with pytest.raises(coordinator.web.InstallError, match="exactly one"):
        coordinator.validate_migration_archive(archive, ({"revision": "20260820_0012", "sha256": "a" * 64},))
    with pytest.raises(coordinator.web.InstallError, match="hash"):
        coordinator.validate_migration_archive(archive, ({"revision": "20260820_0013", "sha256": "a" * 64},))


def test_migration_environment_prevents_root_bytecode_in_staged_release(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    profile = tmp_path / "migration.env"
    profile.write_text(
        "\n".join(
            (
                "EOAT_API_ENVIRONMENT=production",
                "EOAT_API_WRITES_ENABLED=false",
                "EOAT_DB_NAME=eoat_atlas_prod",
                "EOAT_DB_HOST=127.0.0.1",
                "EOAT_DB_PORT=3306",
                "EOAT_DB_MIGRATION_USER=eoat_atlas_migrator",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(coordinator, "MIGRATION_ENVIRONMENT", profile)

    environment = coordinator._migration_environment()

    assert environment["PYTHONDONTWRITEBYTECODE"] == "1"


def test_migration_archive_requires_a_complete_dag_traversal_from_production_head(tmp_path: Path) -> None:
    archive = tmp_path / "server.zip"
    migrations = {
        "20260713_0001": None,
        "20260729_0009": "20260713_0001",
        "20260811_0005": "20260713_0001",
        "20260813_0012": "20260811_0005",
        "20260820_0013": ("20260729_0009", "20260813_0012"),
    }
    approved: list[dict[str, str]] = []
    with zipfile.ZipFile(archive, "w") as bundle:
        for revision, predecessor in migrations.items():
            payload = f"revision: str = {revision!r}\ndown_revision: object = {predecessor!r}\n".encode()
            bundle.writestr(f"server/migrations/versions/{revision}_fixture.py", payload)
            if revision not in {"20260713_0001", "20260729_0009"}:
                approved.append({"revision": revision, "sha256": hashlib.sha256(payload).hexdigest()})
    coordinator.validate_migration_archive(archive, tuple(approved), current="20260729_0009")
    with pytest.raises(coordinator.web.InstallError, match="missing predecessor"):
        coordinator.validate_migration_archive(
            archive,
            tuple(item for item in approved if item["revision"] != "20260813_0012"),
            current="20260729_0009",
        )


def test_multi_migration_failure_restores_the_verified_backup(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    releases = tmp_path / "releases"
    server = releases / "staged"
    server.mkdir(parents=True)
    (server / "venv" / "bin").mkdir(parents=True)
    (server / "venv" / "bin" / "python").write_text("fixture", encoding="utf-8")
    (server / "server").mkdir()
    (server / "server" / "alembic.ini").write_text("[alembic]", encoding="utf-8")
    monkeypatch.setattr(coordinator, "API_RELEASES", releases)
    monkeypatch.setattr(coordinator, "_migration_environment", lambda: {"safe": "environment"})
    observed: list[object] = []
    monkeypatch.setattr(coordinator, "_staged_alembic_current", lambda *_args: "20260729_0009")
    monkeypatch.setattr(
        coordinator,
        "_run_governed",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(coordinator.web.InstallError("migration failed")),
    )
    monkeypatch.setattr(coordinator, "restore_backup", lambda backup: observed.append(backup))
    service_commands: list[list[str]] = []
    monkeypatch.setattr(
        coordinator.subprocess,
        "run",
        lambda command, **_kwargs: service_commands.append(command) or type("Result", (), {"returncode": 0})(),
    )
    backup = {"path": "/fixed/recovery.sql.gz", "sha256": "a" * 64}
    with pytest.raises(coordinator.web.InstallError, match="migration failed"):
        coordinator.apply_migration_plan(
            server,
            ("20260729_0009", "20260820_0013", ({"revision": "20260820_0013", "sha256": "a" * 64},)),
            backup,
        )
    assert observed == [backup]
    assert service_commands == [
        ["/bin/systemctl", "stop", coordinator.SERVICE],
        ["/bin/systemctl", "restart", coordinator.SERVICE],
    ]
