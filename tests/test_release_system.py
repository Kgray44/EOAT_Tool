from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

import pytest

from release_tools.launcher import APP_EXE, LauncherError, install_package, update_and_launch
from release_tools.manifest import read_manifest, sha256_file, validate_manifest
from release_tools.versioning import Version
from scripts.publish_release import PublishError, ReleaseLock, _publish_package, staged_source_metadata


@pytest.mark.parametrize("source,expected", [("0.4.7", "0.4.8"), ("1.2.9", "1.2.10"), ("0.9.9", "0.9.10")])
def test_patch_bump(source, expected):
    assert str(Version.parse(source).bump()) == expected


def test_semantic_comparison_is_numeric():
    assert Version.parse("0.10.0") > Version.parse("0.9.9")


def test_minor_bump_resets_patch():
    assert str(Version.parse("0.9.9").bump("minor")) == "0.10.0"


def test_major_bump_resets_minor_and_patch():
    assert str(Version.parse("1.9.9").bump("major")) == "2.0.0"


@pytest.mark.parametrize("value", ["", "1", "1.2", "1.2.3.4", "01.2.3", "1.2.x", "1.2.3-dev"])
def test_invalid_versions_rejected(value):
    with pytest.raises(ValueError):
        Version.parse(value)


def test_launcher_version_is_independent():
    from release_tools.launcher import LAUNCHER_VERSION

    assert LAUNCHER_VERSION == "0.1.0"
    assert str(Version.parse("0.9.0").bump()) == "0.9.1"


def make_package(root: Path, version: str, *, corrupt_metadata: bool = False) -> tuple[Path, dict]:
    source = root / "source" / "EOAT Atlas"
    source.mkdir(parents=True)
    (source / APP_EXE).write_bytes(b"fake-executable")
    (source / "_internal").mkdir()
    (source / "release_metadata.json").write_text(
        json.dumps({"app_name": "EOAT Atlas", "app_version": "9.9.9" if corrupt_metadata else version}),
        encoding="utf-8",
    )
    package = root / f"EOAT-Atlas_v{version}.zip"
    with zipfile.ZipFile(package, "w") as archive:
        for path in source.rglob("*"):
            if path.is_file():
                archive.write(path, Path("EOAT Atlas") / path.relative_to(source))
    manifest = {
        "latest_version": version,
        "release_path": str(package),
        "minimum_supported_version": "0.1.0",
        "sha256": sha256_file(package),
        "package_size": package.stat().st_size,
        "published_at": "2026-07-13T12:00:00-04:00",
        "release_notes": "test",
    }
    return package, manifest


def install_local(root: Path, version: str) -> Path:
    directory = root / "app_versions" / version
    directory.mkdir(parents=True)
    (directory / APP_EXE).write_bytes(b"local")
    (directory / "release_metadata.json").write_text(json.dumps({"app_version": version}), encoding="utf-8")
    (root / "current.json").write_text(json.dumps({"version": version, "path": str(directory)}), encoding="utf-8")
    return directory


def deploy_manifest(deploy: Path, manifest: dict) -> None:
    path = deploy / "Manifests" / "latest.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(manifest), encoding="utf-8")


def test_manifest_unknown_fields_tolerated(tmp_path):
    _, manifest = make_package(tmp_path, "1.0.0")
    manifest["future_field"] = {"ok": True}
    assert validate_manifest(manifest)["future_field"] == {"ok": True}


@pytest.mark.parametrize(
    "field", ["latest_version", "release_path", "minimum_supported_version", "sha256", "package_size", "published_at"]
)
def test_manifest_required_fields(field, tmp_path):
    _, manifest = make_package(tmp_path, "1.0.0")
    manifest.pop(field)
    with pytest.raises(ValueError):
        validate_manifest(manifest)


def test_bad_checksum_and_size_rejected(tmp_path):
    _, manifest = make_package(tmp_path, "1.0.0")
    path = tmp_path / "latest.json"
    path.write_text(json.dumps(dict(manifest, sha256="0" * 64)), encoding="utf-8")
    with pytest.raises(ValueError, match="checksum"):
        read_manifest(path, require_package=True)
    path.write_text(json.dumps(dict(manifest, package_size=1)), encoding="utf-8")
    with pytest.raises(ValueError, match="size"):
        read_manifest(path, require_package=True)


@pytest.mark.parametrize("suffix", [".partial", ".tmp"])
def test_manifest_never_references_staging_name(tmp_path, suffix):
    _, manifest = make_package(tmp_path, "1.0.0")
    manifest["release_path"] += suffix
    with pytest.raises(ValueError, match="release_path"):
        validate_manifest(manifest)


def test_nonpositive_package_size_rejected(tmp_path):
    _, manifest = make_package(tmp_path, "1.0.0")
    manifest["package_size"] = 0
    with pytest.raises(ValueError, match="positive"):
        validate_manifest(manifest)


def test_missing_local_and_offline_is_actionable(tmp_path):
    with pytest.raises(LauncherError, match="not installed"):
        update_and_launch(tmp_path / "offline", tmp_path / "local", launch=lambda _: None)


def test_install_only_never_launches(tmp_path):
    _, manifest = make_package(tmp_path, "1.0.0")
    deploy, local = tmp_path / "deploy", tmp_path / "local"
    deploy_manifest(deploy, manifest)
    launches = []
    assert update_and_launch(deploy, local, launch=launches.append, install_only=True) == "installed"
    assert launches == []


def test_missing_local_installs_and_launches_once(tmp_path):
    package, manifest = make_package(tmp_path, "1.0.0")
    deploy, local = tmp_path / "deploy", tmp_path / "local"
    deploy_manifest(deploy, manifest)
    launches = []
    assert update_and_launch(deploy, local, launch=launches.append) == "installed"
    assert len(launches) == 1 and launches[0].is_file()


def test_older_updates_once_then_does_not_redownload(tmp_path):
    _, manifest = make_package(tmp_path, "1.0.1")
    deploy, local = tmp_path / "deploy", tmp_path / "local"
    deploy_manifest(deploy, manifest)
    install_local(local, "1.0.0")
    launches = []
    assert update_and_launch(deploy, local, launch=launches.append) == "updated"
    package_mtime = Path(manifest["release_path"]).stat().st_mtime_ns
    assert update_and_launch(deploy, local, launch=launches.append) == "current"
    assert len(launches) == 2 and Path(manifest["release_path"]).stat().st_mtime_ns == package_mtime


def test_newer_local_not_downgraded(tmp_path):
    _, manifest = make_package(tmp_path, "1.0.0")
    deploy, local = tmp_path / "deploy", tmp_path / "local"
    deploy_manifest(deploy, manifest)
    directory = install_local(local, "1.1.0")
    launches = []
    assert update_and_launch(deploy, local, launch=launches.append) == "newer-local"
    assert launches == [directory / APP_EXE]


def test_offline_fallback_and_minimum_enforcement(tmp_path):
    local = tmp_path / "local"
    install_local(local, "1.0.0")
    (local / "last_known_good_manifest.json").write_text(
        json.dumps({"minimum_supported_version": "0.9.0"}), encoding="utf-8"
    )
    assert update_and_launch(tmp_path / "offline", local, launch=lambda _: None) == "offline-fallback"
    (local / "last_known_good_manifest.json").write_text(
        json.dumps({"minimum_supported_version": "1.1.0"}), encoding="utf-8"
    )
    with pytest.raises(LauncherError, match="required"):
        update_and_launch(tmp_path / "offline", local, launch=lambda _: None)


@pytest.mark.parametrize("failure", ["missing", "checksum", "size", "metadata", "zip"])
def test_invalid_update_preserves_local(failure, tmp_path):
    package, manifest = make_package(tmp_path, "1.0.1", corrupt_metadata=failure == "metadata")
    deploy, local = tmp_path / "deploy", tmp_path / "local"
    old = install_local(local, "1.0.0")
    if failure == "missing":
        package.unlink()
    elif failure == "checksum":
        manifest["sha256"] = "0" * 64
    elif failure == "size":
        manifest["package_size"] += 1
    elif failure == "zip":
        package.write_bytes(b"not a zip")
        manifest.update(sha256=sha256_file(package), package_size=package.stat().st_size)
    deploy_manifest(deploy, manifest)
    launches = []
    assert update_and_launch(deploy, local, launch=launches.append) == "update-failed-fallback"
    assert launches == [old / APP_EXE]
    assert json.loads((local / "current.json").read_text())["version"] == "1.0.0"


def test_partial_staging_never_installed_and_user_data_preserved(tmp_path):
    _, manifest = make_package(tmp_path, "1.0.1")
    local = tmp_path / "local"
    install_local(local, "1.0.0")
    protected = [
        local / "settings.json",
        local / "data" / "local_cache.db",
        local / "cache" / "x",
        local / "logs" / "x",
        local / "exports" / "x",
        local / "install_identity.json",
    ]
    for path in protected:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("keep", encoding="utf-8")
    install_package(manifest, local)
    assert all(path.read_text(encoding="utf-8") == "keep" for path in protected)
    assert not (local / "app_staging").exists() or not any((local / "app_staging").iterdir())


def test_concurrent_lock_and_stale_lock_are_safe(tmp_path):
    first = ReleaseLock(tmp_path)
    first.acquire()
    try:
        with pytest.raises(PublishError, match="do not delete"):
            ReleaseLock(tmp_path).acquire()
        lock_path = tmp_path / "Manifests" / "publish.lock"
        old = lock_path.stat().st_mtime - 9 * 3600
        import os

        os.utime(lock_path, (old, old))
        with pytest.raises(PublishError, match="verify the recorded process"):
            ReleaseLock(tmp_path).acquire()
        assert lock_path.exists()
    finally:
        first.release()


def test_publisher_manifest_last_and_previous_recoverable(tmp_path, monkeypatch):
    deploy = tmp_path / "Deployment With Spaces & Ampersand"
    old_package, old_manifest = make_package(tmp_path / "old", "1.0.0")
    current = deploy / "Packages" / "Current"
    current.mkdir(parents=True)
    old_network = current / old_package.name
    shutil.copy2(old_package, old_network)
    old_manifest["release_path"] = str(old_network)
    manifests = deploy / "Manifests"
    manifests.mkdir(parents=True)
    (manifests / "latest.json").write_text(json.dumps(old_manifest), encoding="utf-8")
    new_package, new_manifest = make_package(tmp_path / "new", "1.0.1")
    events = []
    from scripts import publish_release

    original = publish_release.atomic_write_json

    def observed(path, payload):
        assert (current / new_package.name).is_file()
        events.append("manifest")
        return original(path, payload)

    monkeypatch.setattr(publish_release, "atomic_write_json", observed)
    _publish_package(deploy, new_package, new_manifest, old_manifest)
    assert events == ["manifest"]
    assert (deploy / "Packages" / "Archive" / old_package.name).is_file()
    assert (manifests / "latest_v1.0.0.json").is_file()


def test_manifest_failure_restores_previous_package(tmp_path, monkeypatch):
    deploy = tmp_path / "deploy"
    old_package, old_manifest = make_package(tmp_path / "old", "1.0.0")
    current = deploy / "Packages" / "Current"
    current.mkdir(parents=True)
    old_network = current / old_package.name
    shutil.copy2(old_package, old_network)
    old_manifest["release_path"] = str(old_network)
    new_package, new_manifest = make_package(tmp_path / "new", "1.0.1")
    from scripts import publish_release

    monkeypatch.setattr(publish_release, "atomic_write_json", lambda *_: (_ for _ in ()).throw(OSError("copy failure")))
    with pytest.raises(OSError):
        _publish_package(deploy, new_package, new_manifest, old_manifest)
    assert old_network.is_file()
    assert not (current / new_package.name).exists()


def test_source_metadata_rolls_back_on_failure(tmp_path, monkeypatch):
    from scripts import publish_release

    metadata = tmp_path / "release_metadata.json"
    metadata.write_text('{"app_version":"1.0.0"}', encoding="utf-8")
    monkeypatch.setattr(publish_release, "ROOT", tmp_path)
    with pytest.raises(RuntimeError), staged_source_metadata({"app_version": "1.0.1"}):
        assert json.loads(metadata.read_text())["app_version"] == "1.0.1"
        raise RuntimeError("preflight failure")
    assert metadata.read_text(encoding="utf-8") == '{"app_version":"1.0.0"}'


def test_same_version_different_content_rejected(tmp_path):
    deploy = tmp_path / "deploy"
    current = deploy / "Packages" / "Current"
    current.mkdir(parents=True)
    package, manifest = make_package(tmp_path / "one", "1.0.0")
    (current / package.name).write_bytes(b"different")
    with pytest.raises(PublishError, match="different content"):
        _publish_package(deploy, package, manifest, None)


def test_frozen_and_development_runtime_roots_are_separate(monkeypatch, tmp_path):
    from core.globalization import runtime_paths

    monkeypatch.setenv("EOAT_ATLAS_LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(runtime_paths.sys, "frozen", False, raising=False)
    assert runtime_paths.get_runtime_paths().runtime_root.name == "EOAT_Atlas_Dev"
    monkeypatch.setattr(runtime_paths.sys, "frozen", True, raising=False)
    assert runtime_paths.get_runtime_paths().runtime_root.name == "EOAT_Atlas"
