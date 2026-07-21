from __future__ import annotations

import json
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest

from deployment import release_manager, server_updater
from deployment.common import CheckResult, CheckStatus, DeploymentError, sha256_file
from deployment.release_manager import build_deployment_archive, package, validate_deployment_archive
from deployment.server_updater import (
    GitHubRelease,
    ReadonlySSH,
    ReleaseAsset,
    RemoteResult,
    ServerConfig,
    cache_release,
    disk_space_preflight,
    dry_run_receipt,
    migration_summary,
    select_release,
    ssh_host_key_status,
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _repository(root: Path, *, destructive_migration: bool = False) -> tuple[Path, str]:
    defaults = {
        "app_name": "EOAT Atlas",
        "api_contract_version": "1.4.0",
        "database_schema_revision": "20260717_0007",
        "environment": "production",
        "release_channel": "server",
        "launcher_version": "0.1.0",
        "installer_version": "0.1.0",
        "minimum_supported_installer_version": "0.1.0",
        "minimum_supported_launcher_version": "0.1.0",
        "metadata_schema_version": 2,
    }
    _write(root / "release_defaults.json", json.dumps(defaults))
    _write(
        root / "app/atlas/version.json",
        json.dumps({"appName": "EOAT Atlas", "version": "1.2.3", "channel": "development"}),
    )
    _write(root / "launcher/launcher_version.json", json.dumps({"launcher_version": "0.1.0"}))
    _write(root / "installer/installer_config.json", json.dumps({"installer_version": "0.1.0"}))
    _write(
        root / "release_history.json",
        json.dumps(
            {
                "schema_version": 1,
                "releases": [
                    {
                        "application_version": "1.2.3",
                        "release_id": "eoat-atlas-1.2.3",
                        "state": "finalized",
                        "task_id": "fixture",
                        "finalized_at_utc": "2026-07-21T00:00:00Z",
                    }
                ],
            }
        ),
    )
    _write(root / "server/alembic.ini", "[alembic]\nscript_location = server/migrations\n")
    _write(root / "server/eoat_api/__init__.py", "")
    _write(root / "server/eoat_api/app.py", "APP_NAME = 'EOAT Atlas'\n")
    _write(root / "server/migrations/env.py", "")
    dangerous = "\nop.drop_table('obsolete')\n" if destructive_migration else ""
    _write(
        root / "server/migrations/versions/20260717_0007_fixture.py",
        f"revision = '20260717_0007'\ndown_revision = None\n{dangerous}",
    )
    _write(root / "core/__init__.py", "")
    _write(root / "release_tools/__init__.py", "")
    _write(root / "requirements.lock", "")
    _write(root / "requirements.txt", "-r requirements.lock\n")
    _write(root / "requirements.in", "")
    _write(root / "pyproject.toml", "")
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "release-test@example.invalid"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Release Test"], cwd=root, check=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-m", "fixture"], cwd=root, check=True, capture_output=True)
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()
    return root, commit


def test_tar_release_manifest_hash_and_safe_layout(tmp_path: Path) -> None:
    root, commit = _repository(tmp_path / "repo")
    build = build_deployment_archive(root, commit, tmp_path / "output", branch="test/release")
    validated = validate_deployment_archive(build.archive, build.manifest, build.checksum)
    assert validated == build.external
    assert build.archive.name.endswith(".tar.gz")
    assert build.core["commit_sha"] == commit
    assert build.external["artifact"]["sha256"] == sha256_file(build.archive)
    assert build.core["services"] == ["eoat-atlas.service"]
    assert build.core["health_checks"] == ["/api/v1/health", "/api/v1/version", "/api/v1/schema-status"]
    with tarfile.open(build.archive, "r:gz") as archive:
        names = archive.getnames()
    assert "release_manifest.json" in names
    assert all(not name.startswith("/") and ".." not in Path(name).parts for name in names)


def test_archive_hash_mismatch_is_rejected(tmp_path: Path) -> None:
    root, commit = _repository(tmp_path / "repo")
    build = build_deployment_archive(root, commit, tmp_path / "output", branch="test/release")
    build.archive.write_bytes(build.archive.read_bytes() + b"tamper")
    with pytest.raises(DeploymentError, match="SHA-256"):
        validate_deployment_archive(build.archive, build.manifest, build.checksum)


def test_archive_path_traversal_is_rejected_even_with_a_matching_outer_hash(tmp_path: Path) -> None:
    root, commit = _repository(tmp_path / "repo")
    build = build_deployment_archive(root, commit, tmp_path / "output", branch="test/release")
    unsafe = tmp_path / "output" / "unsafe.tar.gz"
    with tarfile.open(unsafe, "w:gz") as archive:
        item = tarfile.TarInfo("../escape")
        item.size = 1
        archive.addfile(item, __import__("io").BytesIO(b"x"))
    external = dict(build.external)
    external["artifact"] = {
        "filename": unsafe.name,
        "format": "tar.gz",
        "sha256": sha256_file(unsafe),
        "size_bytes": unsafe.stat().st_size,
    }
    manifest = tmp_path / "output" / "unsafe-manifest.json"
    manifest.write_text(json.dumps(external), encoding="utf-8")
    checksum = tmp_path / "output" / "unsafe.tar.gz.sha256"
    checksum.write_text(f"{sha256_file(unsafe)}  {unsafe.name}\n", encoding="ascii")
    with pytest.raises(DeploymentError, match="Unsafe archive member"):
        validate_deployment_archive(unsafe, manifest, checksum)


def test_secret_and_forbidden_file_selection_is_rejected(tmp_path: Path) -> None:
    root, _commit = _repository(tmp_path / "repo")
    _write(root / "server/.env", "PASSWORD='do-not-package'\n")
    subprocess.run(["git", "add", "server/.env"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-m", "unsafe fixture"], cwd=root, check=True, capture_output=True)
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True, capture_output=True, check=True
    ).stdout.strip()
    with pytest.raises(DeploymentError, match="safety scan"):
        build_deployment_archive(root, commit, tmp_path / "output", branch="test/release")


def test_release_selection_is_semantic_and_ignores_drafts() -> None:
    assets = (
        ReleaseAsset("release_manifest.json"),
        ReleaseAsset("eoat-atlas-server-0.10.0-abcdef0.tar.gz"),
        ReleaseAsset("eoat-atlas-server-0.10.0-abcdef0.tar.gz.sha256"),
    )
    older = GitHubRelease("v0.9.9", False, False, None, assets)
    newest = GitHubRelease("v0.10.0", False, False, None, assets)
    draft = GitHubRelease("v9.0.0", True, False, None, assets)
    assert select_release([older, draft, newest]).tag == "v0.10.0"
    assert select_release([older, newest], "0.9.9").tag == "v0.9.9"


def test_release_cache_revalidates_and_quarantines_a_corrupt_entry(tmp_path: Path) -> None:
    root, commit = _repository(tmp_path / "repo")
    build = build_deployment_archive(root, commit, tmp_path / "source", branch="test/release")
    assets = tuple(
        ReleaseAsset(path.name, size=path.stat().st_size) for path in (build.manifest, build.archive, build.checksum)
    )
    release = GitHubRelease("v1.2.3", False, False, None, assets)

    def copy_asset(_root: Path, _release: GitHubRelease, asset: ReleaseAsset, destination: Path) -> None:
        shutil.copyfile(build.manifest.parent / asset.name, destination)

    cache = cache_release(root, release, tmp_path / "cache", downloader=copy_asset)
    assert (cache / "verification.json").is_file()
    (cache / build.archive.name).write_bytes(b"corrupt")
    restored = cache_release(root, release, tmp_path / "cache", downloader=copy_asset)
    assert restored == cache
    assert sha256_file(restored / build.archive.name) == build.external["artifact"]["sha256"]
    assert list((tmp_path / "cache").glob("1.2.3.corrupt-*"))


def test_readonly_ssh_rejects_unapproved_commands_and_uses_strict_host_checks() -> None:
    config = ServerConfig(
        "EOAT-ATLAS",
        22,
        "eoat-deploy",
        "/opt/eoat-atlas",
        8765,
        (),
        None,
        "eoat-atlas-prod-runtime",
        "eoat_atlas_prod",
        "/var/lock/eoat-atlas-deploy.lock",
    )
    observed: list[list[str]] = []
    observed_kwargs: list[dict[str, object]] = []

    def fake_runner(command, **kwargs):
        observed.append(command)
        observed_kwargs.append(kwargs)
        return subprocess.CompletedProcess(command, 0, stdout="EOAT-ATLAS\n", stderr="")

    ssh = ReadonlySSH(config, runner=fake_runner)
    assert ssh.execute("hostname").exit_code == 0
    assert "StrictHostKeyChecking=yes" in observed[0]
    assert observed_kwargs[0]["encoding"] == "utf-8"
    assert observed_kwargs[0]["errors"] == "replace"
    assert ssh._command("time") == ["date", "-u", "+%Y-%m-%dT%H:%M:%SZ"]
    assert ssh._command("health", "/api/v1/schema-status")[-1].endswith("/api/v1/schema-status")
    with pytest.raises(DeploymentError, match="not allowlisted"):
        ssh.execute("rm")
    with pytest.raises(DeploymentError, match="not allowlisted"):
        ssh.execute("service", "bad;systemctl restart nginx")


def test_current_deployment_falls_back_to_legacy_release_metadata() -> None:
    manifest = RemoteResult("current-manifest", (), 1, "No such file")
    metadata = RemoteResult(
        "current-metadata",
        (),
        0,
        json.dumps(
            {
                "app_version": "0.17.1",
                "release_id": "eoat-atlas-0.17.1",
                "build_id": "eoat-atlas-0.17.1-b18de78-20260720T201856Z",
                "source_git_commit": "b18de78a6b8ca67b1d22e781aa717366d0bb67a9",
                "build_timestamp": "2026-07-20T20:18:56Z",
                "database_schema_revision": "20260717_0007",
            }
        ),
    )
    current, warnings = server_updater._current_deployment(manifest, metadata)
    assert current["primary_source"] == "release_metadata"
    assert current["identity"]["version"] == "0.17.1"
    assert current["identity"]["commit_sha"] == "b18de78a6b8ca67b1d22e781aa717366d0bb67a9"
    assert warnings


def test_service_discovery_selects_verified_eoat_and_nginx_units() -> None:
    config = ServerConfig(
        "eoat-atlas",
        22,
        "kgray",
        "/opt/eoat-atlas",
        8765,
        (),
        None,
        "eoat-atlas-prod-runtime",
        "eoat_atlas_prod",
        "/var/lock/eoat-atlas-deploy.lock",
    )
    units = RemoteResult(
        "service-units",
        (),
        0,
        "  eoat-atlas.service loaded active running EOAT Atlas API\n  nginx.service loaded active running nginx\n",
    )
    assert server_updater._discovered_service_names(units, config) == ("eoat-atlas.service", "nginx.service")


def test_health_comparison_keeps_http_timing_and_release_identity() -> None:
    core = {"version": "0.17.3", "commit_sha": "a" * 40}
    health = {
        "/api/v1/health": {
            "status": "PASS",
            "output": json.dumps(
                {
                    "application_version": "0.17.1",
                    "release_id": "eoat-atlas-0.17.1",
                    "build_id": "eoat-atlas-0.17.1-build",
                    "current_schema_revision": "20260717_0007",
                    "database_reachable": True,
                }
            )
            + "\n__EOAT_HTTP_STATUS=200 __EOAT_RESPONSE_SECONDS=0.013\n",
        }
    }
    compared, warnings = server_updater.health_comparison(health, core)
    assert compared["/api/v1/health"]["http_status"] == 200
    assert compared["/api/v1/health"]["response_seconds"] == pytest.approx(0.013)
    assert compared["/api/v1/health"]["values"]["release_id"] == "eoat-atlas-0.17.1"
    assert warnings


def test_truth_reconciliation_flags_environment_disagreement() -> None:
    current = {
        "identity": {
            "version": "0.17.1",
            "release_id": "eoat-atlas-0.17.1",
            "build_id": "eoat-atlas-0.17.1-build",
            "commit_sha": "b18de78a6b8ca67b1d22e781aa717366d0bb67a9",
            "migration_revision": "20260717_0007",
            "environment": "production",
        }
    }
    remote = {
        "current-target": RemoteResult(
            "current-target", (), 0, "/opt/eoat-atlas/releases/eoat-atlas-server-0.17.1-b18de78"
        )
    }
    services = {
        "eoat-atlas.service": {
            "status": "PASS",
            "output": "ExecStart=/opt/eoat-atlas/current/venv/bin/python",
        }
    }
    health = {
        "/api/v1/health": {
            "status": "PASS",
            "output": json.dumps(
                {
                    "application_version": "0.17.1",
                    "release_id": "eoat-atlas-0.17.1",
                    "build_id": "eoat-atlas-0.17.1-build",
                    "environment": "development",
                    "current_schema_revision": "20260717_0007",
                }
            ),
        }
    }
    result = server_updater.truth_reconciliation(current, remote, services, health)
    assert any("Environment mismatch" in violation for violation in result["violations"])


def test_unknown_host_key_is_reported_but_never_trusted(monkeypatch: pytest.MonkeyPatch) -> None:
    config = ServerConfig(
        "EOAT-ATLAS",
        22,
        None,
        "/opt/eoat-atlas",
        8765,
        (),
        None,
        "eoat-atlas-prod-runtime",
        "eoat_atlas_prod",
        "/var/lock/eoat-atlas-deploy.lock",
    )

    def fake_run(command, **_kwargs):
        if command[:2] == ["ssh-keygen", "-F"]:
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="")
        if command[0] == "ssh-keyscan":
            return subprocess.CompletedProcess(
                command, 0, stdout="EOAT-ATLAS ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI\n", stderr=""
            )
        if command[:2] == ["ssh-keygen", "-lf"]:
            return subprocess.CompletedProcess(
                command, 0, stdout="256 SHA256:untrusted EOAT-ATLAS (ED25519)\n", stderr=""
            )
        raise AssertionError(command)

    monkeypatch.setattr(server_updater.subprocess, "run", fake_run)
    status = ssh_host_key_status(config)
    assert status.known is False
    assert "SHA256:untrusted" in str(status.fingerprint)


def test_unknown_host_key_falls_back_to_strict_authentication_disabled_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = ServerConfig(
        "EOAT-ATLAS",
        22,
        "eoat-deploy",
        "/opt/eoat-atlas",
        8765,
        (),
        None,
        "eoat-atlas-prod-runtime",
        "eoat_atlas_prod",
        "/var/lock/eoat-atlas-deploy.lock",
    )
    observed: list[list[str]] = []

    def fake_run(command, **_kwargs):
        observed.append(command)
        if command[:2] == ["ssh-keygen", "-F"]:
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="")
        if command[0] == "ssh-keyscan":
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="unsupported KEX")
        if command[0] == "ssh":
            return subprocess.CompletedProcess(
                command,
                255,
                stdout="",
                stderr="debug1: Server host key: ssh-ed25519 SHA256:strictcandidate\n",
            )
        raise AssertionError(command)

    monkeypatch.setattr(server_updater.subprocess, "run", fake_run)
    status = ssh_host_key_status(config)
    assert status.known is False
    assert status.fingerprint == "SHA256:strictcandidate"
    probe = next(command for command in observed if command[0] == "ssh")
    assert "StrictHostKeyChecking=yes" in probe
    assert "PubkeyAuthentication=no" in probe
    assert "PasswordAuthentication=no" in probe


def test_disk_preflight_uses_conservative_estimate() -> None:
    sufficient = disk_space_preflight(
        "Filesystem Size Used Avail Use% Mounted on\n/dev/sda1 20G 1G 19G 5% /opt\n/dev/sda2 10G 1G 9G 10% /tmp\n",
        10 * 1024**2,
    )
    assert sufficient["status"] == "PASS"
    insufficient = disk_space_preflight(
        "Filesystem Size Used Avail Use% Mounted on\n/dev/sda1 1G 900M 124M 90% /opt\n",
        10 * 1024**2,
    )
    assert insufficient["status"] == "FAIL"


def test_migration_preflight_flags_destructive_operations(tmp_path: Path) -> None:
    root, commit = _repository(tmp_path / "repo", destructive_migration=True)
    build = build_deployment_archive(root, commit, tmp_path / "output", branch="test/release")
    summary = migration_summary(build.archive)
    assert summary["heads"] == ["20260717_0007"]
    assert summary["destructive_warnings"]


def test_dry_run_never_attempts_server_mutation(tmp_path: Path) -> None:
    root, commit = _repository(tmp_path / "repo")
    build = build_deployment_archive(root, commit, tmp_path / "output", branch="test/release")
    receipt = dry_run_receipt(root, build.archive.parent, build.external, None)
    assert receipt["mode"] == "DRY_RUN_READ_ONLY"
    assert receipt["mutating_operations_attempted"] is False
    assert receipt["production_files_modified"] is False
    assert receipt["production_service_restarted"] is False
    assert receipt["production_database_written"] is False


def test_package_dry_run_uses_disposable_clone_without_mutating_source(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root, commit = _repository(tmp_path / "repo")
    original_status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=root, text=True, capture_output=True, check=True
    ).stdout
    monkeypatch.setattr(
        release_manager, "run_validation", lambda _root: ([CheckResult("fixture", CheckStatus.PASS, "ok")], [])
    )
    receipt = package(
        root,
        bump="patch",
        explicit_version=None,
        dry_run=True,
        no_push=True,
        no_publish=True,
        allow_dirty=False,
        approved_exception=None,
    )
    assert receipt["final_status"] == "DRY_RUN_SUCCEEDED"
    assert receipt["starting_commit"] == commit
    assert (
        subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True, capture_output=True, check=True
        ).stdout.strip()
        == commit
    )
    assert (
        subprocess.run(["git", "status", "--porcelain"], cwd=root, text=True, capture_output=True, check=True).stdout
        == original_status
    )
