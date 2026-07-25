from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from core.versioning.version_info import get_release_info, validate_release_metadata
from scripts.release import build_server_release as builder


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def release_repository(root: Path) -> tuple[Path, str]:
    defaults = {
        "app_name": "EOAT Atlas",
        "api_contract_version": "1.4.0",
        "database_schema_revision": "20260721_0008",
        "environment": "production",
        "release_channel": "server",
        "launcher_version": "0.1.0",
        "installer_version": "0.1.0",
        "metadata_schema_version": 2,
    }
    _write(root / "release_defaults.json", json.dumps(defaults))
    _write(root / "app/atlas/version.json", json.dumps({"appName": "EOAT Atlas", "version": "1.2.3", "channel": "development"}))
    _write(root / "launcher/launcher_version.json", json.dumps({"launcher_version": "0.1.0"}))
    _write(root / "installer/installer_config.json", json.dumps({"installer_version": "0.1.0"}))
    _write(root / "deployment/migration_identity.py", "")
    _write(root / "deployment/migration_identity_attestations.json", json.dumps({"schema": 1, "attestations": []}))
    _write(root / "server/eoat_api/__init__.py", "")
    _write(root / "server/migrations/versions/20260721_0008_test.py", 'revision = "20260721_0008"\ndown_revision = None\n')
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
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True).stdout.strip()
    return root, commit


def _args(root: Path, output: Path, commit: str = "HEAD") -> argparse.Namespace:
    return argparse.Namespace(
        root=root,
        source_commit=commit,
        branch_name="test/release",
        build_timestamp="2026-07-16T20:00:00Z",
        output_dir=output,
    )


def test_metadata_generation_captures_exact_source_and_stable_identities(tmp_path: Path) -> None:
    root, commit = release_repository(tmp_path / "repo")
    timestamp = datetime(2026, 7, 16, 20, 0, tzinfo=timezone.utc)
    metadata = builder.generate_release_metadata(root, commit, branch_name="test/release", build_timestamp=timestamp)
    assert metadata["app_version"] == "1.2.3"
    assert metadata["release_id"] == "eoat-atlas-1.2.3"
    assert metadata["build_id"] == f"eoat-atlas-1.2.3-{commit[:7]}-20260716T200000Z"
    assert metadata["source_git_commit"] == metadata["git_commit"] == commit
    assert metadata["database_schema_revision"] == "20260721_0008"
    assert metadata["api_contract_version"] == "1.4.0"
    assert metadata["build_timestamp"] == "2026-07-16T20:00:00Z"


def test_invalid_commit_and_invalid_repository_are_rejected(tmp_path: Path) -> None:
    root, _ = release_repository(tmp_path / "repo")
    with pytest.raises(builder.ReleaseBuildError):
        builder.resolve_source_commit(root, "not-a-commit")
    with pytest.raises(builder.ReleaseBuildError, match="Not a Git repository"):
        builder.resolve_source_commit(tmp_path / "not-a-repo", "HEAD")


def test_missing_git_executable_is_reported(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)

    def missing(*_args, **_kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr(builder.subprocess, "run", missing)
    with pytest.raises(builder.ReleaseBuildError, match="Git executable"):
        builder.resolve_source_commit(root, "HEAD")


def test_relevant_dirty_files_block_but_unrelated_dirty_files_do_not(tmp_path: Path) -> None:
    root, commit = release_repository(tmp_path / "repo")
    _write(root / "server/eoat_api/__init__.py", "DIRTY = True\n")
    with pytest.raises(builder.ReleaseBuildError, match="Relevant uncommitted"):
        builder.build_server_release(_args(root, tmp_path / "blocked", commit))
    subprocess.run(["git", "restore", "server/eoat_api/__init__.py"], cwd=root, check=True)
    _write(root / "notes/ui-work.txt", "unrelated work\n")
    archive, _, _, manifest = builder.build_server_release(_args(root, tmp_path / "output with spaces", commit))
    assert archive.is_file()
    assert manifest["source_git_commit"] == commit


def test_archive_checksum_manifest_and_linux_layout_are_consistent(tmp_path: Path) -> None:
    root, commit = release_repository(tmp_path / "repo")
    archive, checksum, manifest_path, manifest = builder.build_server_release(_args(root, tmp_path / "dist", commit))
    assert checksum.read_text(encoding="ascii").strip() == f"{builder.sha256_file(archive)}  {archive.name}"
    assert json.loads(manifest_path.read_text(encoding="utf-8")) == manifest
    assert manifest["archive_sha256"] == builder.sha256_file(archive)
    with zipfile.ZipFile(archive) as package:
        assert package.testzip() is None
        assert all("\\" not in name and not name.startswith("/") for name in package.namelist())
        metadata = json.loads(package.read("release_metadata.json"))
    assert metadata["source_git_commit"] == commit
    assert metadata["database_schema_revision"] == "20260721_0008"
    assert metadata["api_contract_version"] == "1.4.0"
    assert not any(builder.SECRET_KEY.search(key) for key in metadata)
    assert not any(builder.SECRET_KEY.search(key) for key in manifest)
    assert manifest["migration_inventory"]
    assert all(item["git_blob_sha256"] == item["staged_file_sha256"] == item["zip_embedded_sha256"] for item in manifest["migration_inventory"].values())


def test_archive_migrations_are_git_bytes_even_when_worktree_is_crlf(tmp_path: Path) -> None:
    root, commit = release_repository(tmp_path / "repo")
    migration = root / "server/migrations/versions/20260721_0008_test.py"
    migration.write_bytes(migration.read_bytes().replace(b"\n", b"\r\n"))
    subprocess.run(["git", "update-index", "--assume-unchanged", migration.relative_to(root).as_posix()], cwd=root, check=True)
    archive, _, _, manifest = builder.build_server_release(_args(root, tmp_path / "dist", commit))
    expected = builder.migration_hashes(root, commit)
    assert builder.archive_migration_hashes(archive) == expected
    assert manifest["migration_inventory"][next(iter(expected))]["git_blob_sha256"] == next(iter(expected.values()))


def test_same_commit_and_timestamp_produce_identical_archives(tmp_path: Path) -> None:
    root, commit = release_repository(tmp_path / "repo")
    first, *_ = builder.build_server_release(_args(root, tmp_path / "one", commit))
    second, *_ = builder.build_server_release(_args(root, tmp_path / "two", commit))
    assert first.read_bytes() == second.read_bytes()


def test_runtime_loads_without_git_and_rejects_metadata_mismatch(tmp_path: Path) -> None:
    root, commit = release_repository(tmp_path / "repo")
    archive, *_ = builder.build_server_release(_args(root, tmp_path / "dist", commit))
    extracted = tmp_path / "linux-release"
    with zipfile.ZipFile(archive) as package:
        package.extractall(extracted)
    shutil.rmtree(extracted / ".git", ignore_errors=True)
    get_release_info.cache_clear()
    info = get_release_info(extracted)
    assert info.source_git_commit == commit
    assert info.metadata_role == "release_artifact"
    payload = json.loads((extracted / "release_metadata.json").read_text(encoding="utf-8"))
    payload["source_git_commit"] = "f" * 40
    with pytest.raises(RuntimeError, match="compatibility alias"):
        validate_release_metadata(payload)
    payload["source_git_commit"] = payload["git_commit"]
    payload["api_contract_version"] = "9.9.9"
    with pytest.raises(RuntimeError, match="API contract"):
        validate_release_metadata(payload)


def test_manifest_secret_fields_are_rejected() -> None:
    with pytest.raises(builder.ReleaseBuildError, match="secret field"):
        builder._assert_no_secret_fields({"database_password": "not-allowed"}, label="manifest")
