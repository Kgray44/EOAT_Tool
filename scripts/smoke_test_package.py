from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EXE = ROOT / "dist" / "EOAT Atlas" / "EOAT Atlas.exe"
FORBIDDEN_PACKAGE_NAMES = (
    "run_" + "dashboard",
    "EOAT_" + "Command_" + "Center",
    "eoat_" + "command_" + "center",
    "dashboard" + "_ui",
    "atlas" + "_window",
)
RUNTIME_ARTIFACT_NAMES = {
    "local_cache.db",
    "local_cache.previous.db",
    "cache_manifest.json",
    "install_identity.json",
    "settings.json",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Smoke test a built EOAT Atlas onedir package.")
    parser.add_argument("exe", nargs="?", default=str(DEFAULT_EXE), help="Path to dist/EOAT Atlas/EOAT Atlas.exe")
    parser.add_argument("--timeout", type=int, default=int(os.environ.get("EOAT_ATLAS_PACKAGE_SMOKE_TIMEOUT_SECONDS", "90")))
    args = parser.parse_args(argv)

    exe = Path(args.exe)
    if not exe.exists():
        print(f"FAIL packaged executable not found: {exe}")
        print("This script is intended for the post-onedir phase after PyInstaller has created dist\\EOAT Atlas.")
        return 1
    package_dir = exe.parent
    failures: list[str] = []
    _check_package_folder(package_dir, failures)

    with tempfile.TemporaryDirectory(prefix="eoat_atlas_package_smoke_") as temp_root:
        runtime_base = Path(temp_root) / "LocalAppData"
        env = os.environ.copy()
        env["EOAT_ATLAS_SMOKE_TEST"] = "1"
        env["EOAT_ATLAS_SMOKE_RUNTIME_PROBE"] = "1"
        env["EOAT_ATLAS_LOCALAPPDATA"] = str(runtime_base)
        env["EOAT_ATLAS_DATA_BACKEND"] = "legacy"
        env.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            completed = subprocess.run([str(exe), "--smoke-test"], cwd=Path.home(), env=env, timeout=args.timeout)
        except subprocess.TimeoutExpired:
            print(f"FAIL packaged app did not exit within {args.timeout} seconds")
            return 1
        if completed.returncode != 0:
            failures.append(f"packaged app exited {completed.returncode}")
        _check_runtime_probe(runtime_base, failures)

    if failures:
        for failure in failures:
            print(f"FAIL {failure}")
        return 1
    print("PASS packaged EOAT Atlas smoke checks passed")
    return 0


def _check_package_folder(package_dir: Path, failures: list[str]) -> None:
    metadata_files = list(package_dir.rglob("release_metadata.json"))
    if len(metadata_files) != 1:
        failures.append(f"expected exactly one release_metadata.json, found {len(metadata_files)}")
    elif (package_dir / "EOAT Atlas.exe").is_file():
        try:
            metadata = json.loads(metadata_files[0].read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            failures.append("release_metadata.json is unreadable or invalid")
        else:
            executable_hash = _sha256(package_dir / "EOAT Atlas.exe")
            if metadata.get("artifact_sha256") != executable_hash:
                failures.append("release metadata artifact SHA-256 does not match the executable")
            if metadata.get("dirty_tree") is not False:
                failures.append("production-candidate metadata does not declare a clean tree")
            if len(str(metadata.get("git_commit") or "")) != 40:
                failures.append("release metadata does not contain an exact Git commit")
    for path in package_dir.rglob("*"):
        name = path.name
        if any(token.casefold() in name.casefold() for token in FORBIDDEN_PACKAGE_NAMES):
            failures.append(f"old app artifact present in package: {path}")
        if name in RUNTIME_ARTIFACT_NAMES:
            failures.append(f"runtime artifact present in package folder: {path}")
        if path.is_dir() and name in {"pending", "events", "logs", "staging", "backups", "thumbnails"}:
            failures.append(f"runtime directory present in package folder: {path}")


def _sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _check_runtime_probe(runtime_base: Path, failures: list[str]) -> None:
    runtime = runtime_base / "EOAT_Atlas"
    if not runtime.exists():
        failures.append(f"runtime folder was not created under LocalAppData override: {runtime}")
        return
    identity_path = runtime / "install_identity.json"
    db_path = runtime / "data" / "local_cache.db"
    pending_dir = runtime / "pending"
    event_dir = runtime / "events" / "outbox"
    for label, path in (
        ("install identity", identity_path),
        ("SQLite cache", db_path),
        ("pending directory", pending_dir),
        ("event outbox directory", event_dir),
    ):
        if not path.exists():
            failures.append(f"{label} missing from runtime: {path}")
    pending_files = list(pending_dir.glob("*.json")) if pending_dir.exists() else []
    event_files = list(event_dir.glob("*.json")) if event_dir.exists() else []
    if not pending_files:
        failures.append("smoke runtime probe did not create a pending update")
    if not event_files:
        failures.append("smoke runtime probe did not create an event JSON")
    if identity_path.exists():
        try:
            identity = json.loads(identity_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            failures.append("install identity is not valid JSON")
        else:
            if identity.get("app_name") != "EOAT Atlas" or not identity.get("install_id"):
                failures.append("install identity does not contain EOAT Atlas identity fields")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
