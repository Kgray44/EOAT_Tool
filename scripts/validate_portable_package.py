"""Validate an EOAT Atlas portable package without using an installer or PowerShell."""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXECUTABLE_NAME = "EOAT Atlas.exe"
REQUIRED_PROFILE = {
    "environment": "production",
    "backend": "mysql_api",
    "api_url": "http://eoat-atlas.gwplastics.com/api/v1",
    "writes_enabled": False,
    "expected_api_version": "1.4.0",
    "expected_schema_revision": "20260717_0007",
    "cache_filename": "eoat_atlas_api_cache.db",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validation_failures(portable_dir: Path, zip_path: Path) -> list[str]:
    failures: list[str] = []
    executable = portable_dir / EXECUTABLE_NAME
    if not executable.is_file():
        failures.append(f"portable executable missing: {executable}")
        return failures
    profile_files = sorted(portable_dir.rglob("production.json"))
    if len(profile_files) != 1:
        failures.append(f"expected exactly one bundled production.json, found {len(profile_files)}")
        profile = {}
    else:
        try:
            profile = json.loads(profile_files[0].read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            failures.append(f"production profile is unreadable: {exc}")
            profile = {}
    if profile != REQUIRED_PROFILE:
        failures.append("portable production profile does not match the approved API contract")
    for required_name in ("PORTABLE_README.txt", "THIRD_PARTY_NOTICES.txt", "portable_manifest.json", "package_manifest.json"):
        if not (portable_dir / required_name).is_file():
            failures.append(f"portable package is missing {required_name}")
    if (portable_dir / "config" / "development.json").exists():
        failures.append("development configuration was included in portable package")
    relative_files = [path.relative_to(portable_dir).as_posix().casefold() for path in portable_dir.rglob("*") if path.is_file()]
    for forbidden in ("pymysql", "sqlalchemy"):
        if any(forbidden in path for path in relative_files):
            failures.append(f"direct database dependency is present in portable package: {forbidden}")
    if any(path.endswith(".ps1") for path in relative_files):
        failures.append("PowerShell script was included in portable package")
    if any(path.endswith((".db", ".sqlite", ".sqlite3")) for path in relative_files):
        failures.append("runtime cache or database was included in portable package")
    if any(path.endswith((".env", "database.env")) for path in relative_files):
        failures.append("environment/credential file was included in portable package")
    metadata_files = sorted(portable_dir.rglob("release_metadata.json"))
    if len(metadata_files) != 1:
        failures.append(f"expected exactly one bundled release_metadata.json, found {len(metadata_files)}")
        metadata = {}
    else:
        try:
            metadata = json.loads(metadata_files[0].read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            failures.append(f"release metadata is unreadable: {exc}")
            metadata = {}
    if metadata.get("artifact_sha256") != sha256(executable):
        failures.append("release metadata executable SHA-256 does not match")
    try:
        manifest = json.loads((portable_dir / "portable_manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        failures.append(f"portable manifest is unreadable: {exc}")
        manifest = {}
    if manifest.get("executable", {}).get("sha256") != sha256(executable):
        failures.append("portable manifest executable SHA-256 does not match")
    if any(manifest.get(key) is not False for key in ("installer_required", "powershell_required", "administrator_required", "python_required", "direct_mysql_connection")):
        failures.append("portable manifest does not declare its required standalone safety properties")
    if not zip_path.is_file():
        failures.append(f"portable ZIP missing: {zip_path}")
        return failures
    try:
        with zipfile.ZipFile(zip_path) as archive:
            bad_member = archive.testzip()
            if bad_member:
                failures.append(f"portable ZIP integrity failure: {bad_member}")
            expected = f"{portable_dir.name}/{EXECUTABLE_NAME}"
            if expected not in archive.namelist():
                failures.append("portable ZIP does not contain the directly runnable executable")
    except (OSError, zipfile.BadZipFile) as exc:
        failures.append(f"portable ZIP is unreadable: {exc}")
    return failures


def _is_admin() -> bool:
    if os.name != "nt":
        return False
    return bool(ctypes.windll.shell32.IsUserAnAdmin())


def launch_from_extracted_space_path(portable_dir: Path, zip_path: Path, timeout_seconds: int) -> list[str]:
    failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="EOAT Atlas Portable Validation ") as temporary:
        temporary_root = Path(temporary)
        extracted_root = temporary_root / "Extracted Portable App With Spaces"
        with zipfile.ZipFile(zip_path) as archive:
            archive.extractall(extracted_root)
        extracted_dir = extracted_root / portable_dir.name
        executable = extracted_dir / EXECUTABLE_NAME
        if not executable.is_file():
            return ["ZIP extraction did not create the directly runnable executable"]
        if _is_admin():
            failures.append("validation process is elevated; non-admin launch evidence is unavailable")
        env = os.environ.copy()
        for key in (
            "EOAT_ATLAS_PACKAGED_TEST_MODE",
            "EOAT_ATLAS_DATA_BACKEND",
            "EOAT_ATLAS_API_URL",
            "EOAT_ATLAS_ENVIRONMENT",
            "EOAT_ATLAS_WRITES_ENABLED",
            "EOAT_ATLAS_API_CACHE",
            "EOAT_ATLAS_RUNTIME_FOLDER_NAME",
        ):
            env.pop(key, None)
        env["EOAT_ATLAS_LOCALAPPDATA"] = str(temporary_root / "Local App Data")
        env["QT_QPA_PLATFORM"] = "offscreen"
        process = subprocess.Popen([str(executable)], cwd=extracted_dir, env=env)
        cache_path = temporary_root / "Local App Data" / "EOAT_Atlas" / "data" / "eoat_atlas_api_cache.db"
        deadline = time.monotonic() + timeout_seconds
        try:
            while time.monotonic() < deadline:
                return_code = process.poll()
                if return_code is not None:
                    failures.append(f"frozen executable exited before production cache creation: {return_code}")
                    break
                if cache_path.is_file() and cache_path.stat().st_size > 0:
                    break
                time.sleep(0.5)
            else:
                failures.append("frozen executable did not create the production API cache before timeout")
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
        if not cache_path.is_file():
            failures.append("frozen executable did not use the production cache path")
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate a directly runnable EOAT Atlas portable package.")
    parser.add_argument("portable_dir", type=Path)
    parser.add_argument("zip_path", type=Path)
    parser.add_argument("--launch", action="store_true", help="Extract to a path containing spaces and launch the frozen executable.")
    parser.add_argument("--timeout", type=int, default=90)
    args = parser.parse_args(argv)

    failures = validation_failures(args.portable_dir, args.zip_path)
    if args.launch and not failures:
        failures.extend(launch_from_extracted_space_path(args.portable_dir, args.zip_path, args.timeout))
    if failures:
        for failure in failures:
            print(f"FAIL {failure}")
        return 1
    print("PASS portable package structure, ZIP extraction, and frozen launch validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
