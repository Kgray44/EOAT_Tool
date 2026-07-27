from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from launcher import LAUNCHER_VERSION

from .manifest import read_manifest, sha256_file
from .release_identity import ArtifactDisposition, read_signed_envelope, verify_manifest
from .versioning import Version

APP_EXE = "EOAT Atlas.exe"
METADATA = "release_metadata.json"
DEFAULT_DEPLOYMENT_ROOT = Path(os.getenv("EOAT_ATLAS_DEPLOYMENT_ROOT", r"C:\Sanitized\ConfigureDeploymentRoot"))


class LauncherError(RuntimeError):
    pass


def _local_root(value: str | None = None) -> Path:
    if value:
        return Path(value)
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    return base / "EOAT_Atlas"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _metadata_path(directory: Path) -> Path:
    direct = directory / METADATA
    return direct if direct.is_file() else directory / "_internal" / METADATA


def _installed(root: Path) -> tuple[Version | None, Path | None]:
    current = _read_json(root / "current.json")
    version_text = current.get("version")
    directory = Path(current.get("path", "")) if current.get("path") else None
    if not version_text or directory is None or not (directory / APP_EXE).is_file():
        return None, None
    try:
        version = Version.parse(version_text)
    except ValueError:
        return None, None
    metadata = _read_json(_metadata_path(directory))
    if metadata.get("app_version") != str(version):
        return None, None
    if current.get("release_id") and metadata.get("release_id") != current.get("release_id"):
        return None, None
    if current.get("build_id") and metadata.get("build_id") != current.get("build_id"):
        return None, None
    return version, directory


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
        Path(name).replace(path)
    except Exception:
        Path(name).unlink(missing_ok=True)
        raise


def install_package(manifest: dict[str, Any], root: Path) -> Path:
    version = Version.parse(manifest["latest_version"])
    package = Path(manifest["release_path"])
    # Keep extraction paths short for Windows MAX_PATH-sensitive dependencies.
    # LOCALAPPDATA and TEMP are normally on the same volume, preserving an
    # atomic directory rename into the version store.
    work = Path(tempfile.mkdtemp(prefix="EAU_"))
    downloaded = work / package.name
    extracted = work / "extracted"
    try:
        shutil.copy2(package, downloaded)
        if downloaded.stat().st_size != manifest["package_size"]:
            raise LauncherError("Downloaded update size did not match the manifest")
        if sha256_file(downloaded).lower() != manifest["sha256"].lower():
            raise LauncherError("Downloaded update checksum did not match the manifest")
        with zipfile.ZipFile(downloaded) as archive:
            archive.extractall(extracted)
        candidates = [p.parent for p in extracted.rglob(APP_EXE)]
        if len(candidates) != 1:
            raise LauncherError("Update package must contain exactly one EOAT Atlas.exe")
        source = candidates[0]
        metadata = _read_json(_metadata_path(source))
        if metadata.get("app_version") != str(version):
            raise LauncherError("Update package embedded version does not match the manifest")
        if metadata.get("release_id") != manifest["release_id"]:
            raise LauncherError("Update package embedded release ID does not match the manifest")
        if metadata.get("build_id") != manifest["build_id"]:
            raise LauncherError("Update package embedded build ID does not match the manifest")
        if (source / APP_EXE).stat().st_size <= 0:
            raise LauncherError("Update executable is empty")
        versions = root / "app_versions"
        versions.mkdir(parents=True, exist_ok=True)
        target = versions / str(version)
        if target.exists():
            existing = _read_json(_metadata_path(target))
            if existing.get("app_version") != str(version) or not (target / APP_EXE).is_file():
                raise LauncherError(f"Existing local version directory is invalid: {target}")
            if (
                existing.get("release_id") != manifest["release_id"]
                or existing.get("build_id") != manifest["build_id"]
            ):
                raise LauncherError(
                    "A different immutable build already occupies the local application-version directory"
                )
        else:
            source.replace(target)
        _write_json_atomic(
            root / "current.json",
            {
                "version": str(version),
                "release_id": manifest["release_id"],
                "build_id": manifest["build_id"],
                "path": str(target),
                "activated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            },
        )
        _write_json_atomic(root / "last_known_good_manifest.json", manifest)
        return target
    finally:
        shutil.rmtree(work, ignore_errors=True)


def install_signed_release_set(
    envelope: dict[str, Any],
    *,
    transport_root: str,
    root: Path,
    trusted_public_keys: dict[str, str],
    revoked_key_ids: set[str] | None = None,
    smoke_timeout_seconds: float = 90.0,
) -> Path:
    """Install, smoke-test, then atomically activate the signed desktop artifact.

    The transport root is intentionally excluded from the signed product
    identity.  A caller may use a HTTPS URL or a compatibility share without
    changing the immutable release set.
    """

    manifest, signature = read_signed_envelope(envelope)
    keys = {key_id: base64.b64decode(value.encode("ascii"), validate=True) for key_id, value in trusted_public_keys.items()}
    verify_manifest(manifest, signature, trusted_public_keys=keys, revoked_key_ids=frozenset(revoked_key_ids or set()))
    identity = manifest.identity
    if identity.product_version in manifest.revoked_product_versions:
        raise LauncherError("The approved release policy revokes this desktop product version")
    desktop = next(item for item in manifest.artifacts if item.component == "desktop")
    if desktop.disposition is not ArtifactDisposition.BUILT:
        raise LauncherError("The approved release set does not contain an installable desktop artifact")
    old_version, _old_dir = _installed(root)
    target_version = Version.parse(identity.product_version)
    if old_version is not None and old_version > target_version:
        raise LauncherError("Automatic downgrade is blocked by release policy")
    if old_version is not None and old_version == target_version:
        return root / "app_versions" / str(target_version)

    work = Path(tempfile.mkdtemp(prefix="EAU_signed_"))
    try:
        downloaded = work / desktop.filename
        _fetch_artifact(transport_root, desktop.filename, downloaded)
        if downloaded.stat().st_size != desktop.size_bytes or sha256_file(downloaded).lower() != desktop.sha256.lower():
            raise LauncherError("Signed release-set desktop artifact did not match its immutable digest")
        extracted = work / "extracted"
        _safe_extract_zip(downloaded, extracted)
        candidates = [path.parent for path in extracted.rglob(APP_EXE)]
        if len(candidates) != 1:
            raise LauncherError("Desktop package must contain exactly one EOAT Atlas executable")
        candidate = candidates[0]
        _validate_embedded_identity(candidate, identity.to_dict())
        _validate_package_file_manifest(candidate)
        versions = root / "app_versions"
        versions.mkdir(parents=True, exist_ok=True)
        target = versions / str(target_version)
        if target.exists():
            _validate_embedded_identity(target, identity.to_dict())
        else:
            candidate.replace(target)
        _smoke_test_candidate(target / APP_EXE, identity.to_dict(), timeout=smoke_timeout_seconds)
        _write_json_atomic(
            root / "current.json",
            {
                "version": identity.product_version,
                "release_id": identity.release_id,
                "build_id": identity.build_id,
                "path": str(target),
                "activated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "release_set_digest": manifest.digest(),
            },
        )
        _write_json_atomic(root / "last_known_good_manifest.json", envelope)
        return target
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _fetch_artifact(transport_root: str, filename: str, destination: Path) -> None:
    source = transport_root.rstrip("/") + "/" + filename
    if transport_root.casefold().startswith(("http://", "https://")):
        import urllib.request

        with urllib.request.urlopen(source, timeout=30) as response, destination.open("wb") as target:
            shutil.copyfileobj(response, target)
        return
    artifact = Path(transport_root) / filename
    shutil.copy2(artifact, destination)


def _safe_extract_zip(archive_path: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    seen: set[str] = set()
    with zipfile.ZipFile(archive_path) as archive:
        for member in archive.infolist():
            name = member.filename.replace("\\", "/")
            normalized = Path(name)
            if not name or name.startswith("/") or ".." in normalized.parts or normalized.is_absolute():
                raise LauncherError(f"Unsafe archive member: {member.filename}")
            if name.casefold() in seen:
                raise LauncherError(f"Duplicate normalized archive member: {member.filename}")
            seen.add(name.casefold())
            mode = member.external_attr >> 16
            if mode and (mode & 0o170000) == 0o120000:
                raise LauncherError(f"Symlinks are forbidden in desktop packages: {member.filename}")
            target = destination / normalized
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)


def _validate_embedded_identity(directory: Path, identity: dict[str, str]) -> None:
    metadata = _read_json(_metadata_path(directory))
    expected = {"app_version": identity["product_version"], "release_id": identity["release_id"], "build_id": identity["build_id"]}
    if any(metadata.get(key) != value for key, value in expected.items()):
        raise LauncherError("Desktop package embedded release identity contradicts the signed release set")


def _validate_package_file_manifest(directory: Path) -> None:
    payload = _read_json(directory / "package_manifest.json")
    files = payload.get("files") if isinstance(payload, dict) else None
    if not isinstance(files, list) or not files:
        raise LauncherError("Desktop package does not include a file manifest")
    for item in files:
        if not isinstance(item, dict):
            raise LauncherError("Desktop package file manifest is malformed")
        relative = Path(str(item.get("path") or ""))
        path = directory / relative
        if not relative.parts or ".." in relative.parts or not path.is_file() or sha256_file(path) != item.get("sha256"):
            raise LauncherError("Desktop package file manifest detected a mutation")


def _smoke_test_candidate(executable: Path, identity: dict[str, str], *, timeout: float) -> None:
    receipt = executable.parent / ".candidate-smoke-receipt.json"
    receipt.unlink(missing_ok=True)
    environment = os.environ.copy()
    environment.update({"EOAT_ATLAS_SMOKE_TEST": "1", "QT_QPA_PLATFORM": "offscreen"})
    result = subprocess.run(
        [str(executable), "--smoke-test", "--smoke-receipt", str(receipt)],
        cwd=executable.parent,
        env=environment,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    try:
        payload = _read_json(receipt)
    finally:
        receipt.unlink(missing_ok=True)
    if result.returncode or payload.get("status") != "passed" or any(
        payload.get(key) != value for key, value in {"application_version": identity["product_version"], "release_id": identity["release_id"], "build_id": identity["build_id"]}.items()
    ):
        raise LauncherError("Candidate desktop smoke test did not produce a matching success receipt")


def update_and_launch(
    deployment_root: Path,
    local_root: Path,
    *,
    launch: Callable[[Path], Any] | None = None,
    install_only: bool = False,
) -> str:
    local_version, local_dir = _installed(local_root)
    try:
        manifest = read_manifest(deployment_root / "Manifests" / "latest.json")
        latest = Version.parse(manifest["latest_version"])
        minimum = Version.parse(manifest["minimum_supported_version"])
    except Exception as exc:
        if local_version is None or local_dir is None:
            raise LauncherError(f"EOAT Atlas is not installed and the update network is unavailable: {exc}") from exc
        cached = _read_json(local_root / "last_known_good_manifest.json")
        try:
            cached_minimum = Version.parse(cached.get("minimum_supported_version", "0.0.0"))
        except ValueError:
            cached_minimum = Version(0, 0, 0)
        if local_version < cached_minimum:
            raise LauncherError("A required EOAT Atlas update is unavailable. Reconnect to the company network and try again.") from exc
        target = local_dir
        action = "offline-fallback"
    else:
        if local_version is None or local_dir is None or local_version < latest:
            print(
                f"Updating EOAT Atlas from v{local_version or 'not installed'} "
                f"to {manifest['release_id']} ({manifest['build_id']})..."
            )
            try:
                target = install_package(manifest, local_root)
            except Exception as exc:
                # A publisher may have archived the package named by a manifest
                # read immediately before latest.json changed. Re-read once.
                try:
                    refreshed = read_manifest(deployment_root / "Manifests" / "latest.json")
                    if refreshed["latest_version"] != manifest["latest_version"] or refreshed["release_path"] != manifest["release_path"]:
                        target = install_package(refreshed, local_root)
                        action = "installed" if local_version is None else "updated"
                        exc = None
                except Exception:
                    pass
                if exc is None:
                    pass
                elif local_version is not None and local_dir is not None and local_version >= minimum:
                    target, action = local_dir, "update-failed-fallback"
                else:
                    raise LauncherError(f"The required EOAT Atlas update could not be installed: {exc}") from exc
            else:
                action = "installed" if local_version is None else "updated"
        else:
            target = local_dir
            action = "current" if local_version == latest else "newer-local"
    if not install_only:
        print("Starting EOAT Atlas...")
        (launch or (lambda exe: subprocess.Popen([str(exe)], cwd=exe.parent)))(target / APP_EXE)
    return action


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=f"EOAT Atlas Launcher {LAUNCHER_VERSION}")
    parser.add_argument("--deployment-root", default=os.environ.get("EOAT_ATLAS_DEPLOYMENT_ROOT", str(DEFAULT_DEPLOYMENT_ROOT)))
    parser.add_argument("--local-root", default=os.environ.get("EOAT_ATLAS_INSTALL_ROOT", ""))
    parser.add_argument("--install-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        print("Checking for updates...")
        update_and_launch(Path(args.deployment_root), _local_root(args.local_root), install_only=args.install_only)
        return 0
    except Exception as exc:
        root = _local_root(args.local_root)
        log_dir = root / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        with (log_dir / "launcher.log").open("a", encoding="utf-8") as stream:
            stream.write(f"{datetime.now().astimezone().isoformat()} ERROR {type(exc).__name__}: {exc}\n")
        print(f"EOAT Atlas could not start: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
