from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .manifest import read_manifest, sha256_file
from .versioning import Version

APP_EXE = "EOAT Atlas.exe"
METADATA = "release_metadata.json"
LAUNCHER_VERSION = "0.1.0"
DEFAULT_DEPLOYMENT_ROOT = Path(r"\\example.invalid\VT\Plant4\Maintenance & Manufacturing Engineering\EOAT Atlas")


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
        if (source / APP_EXE).stat().st_size <= 0:
            raise LauncherError("Update executable is empty")
        versions = root / "app_versions"
        versions.mkdir(parents=True, exist_ok=True)
        target = versions / str(version)
        if target.exists():
            existing = _read_json(_metadata_path(target))
            if existing.get("app_version") != str(version) or not (target / APP_EXE).is_file():
                raise LauncherError(f"Existing local version directory is invalid: {target}")
        else:
            source.replace(target)
        _write_json_atomic(root / "current.json", {"version": str(version), "path": str(target), "activated_at": datetime.now().astimezone().isoformat(timespec="seconds")})
        _write_json_atomic(root / "last_known_good_manifest.json", manifest)
        return target
    finally:
        shutil.rmtree(work, ignore_errors=True)


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
            print(f"Updating EOAT Atlas from v{local_version or 'not installed'} to v{latest}...")
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
