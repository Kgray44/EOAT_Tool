from __future__ import annotations

import argparse
import getpass
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import uuid
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from release_tools.manifest import atomic_write_json, read_manifest, sha256_file, validate_manifest
from release_tools.versioning import Version, build_identifier

DEFAULT_DEPLOYMENT_ROOT = Path(os.getenv("EOAT_ATLAS_DEPLOYMENT_ROOT", r"C:\Sanitized\ConfigureDeploymentRoot"))


class PublishError(RuntimeError):
    pass


class ReleaseLock:
    def __init__(self, deployment_root: Path, stale_hours: int = 8) -> None:
        self.path = deployment_root / "Manifests" / "publish.lock"
        self.stale_hours = stale_hours
        self.owned = False

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"pid": os.getpid(), "host": socket.gethostname(), "user": getpass.getuser(), "created_at": datetime.now().astimezone().isoformat()}
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            age = time.time() - self.path.stat().st_mtime
            detail = self.path.read_text(encoding="utf-8", errors="replace")[:1000]
            stale = age > self.stale_hours * 3600
            advice = " It appears stale; verify the recorded process is not active, then remove it deliberately." if stale else " Another publisher may be active; do not delete this lock."
            raise PublishError(f"Release lock already exists: {self.path}.{advice} Lock record: {detail}") from exc
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2)
        self.owned = True

    def release(self) -> None:
        if self.owned:
            self.path.unlink(missing_ok=True)
            self.owned = False

    def __enter__(self) -> ReleaseLock:
        self.acquire()
        return self

    def __exit__(self, *_: object) -> None:
        self.release()


def _read_source_metadata() -> dict[str, Any]:
    path = ROOT / "release_metadata.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PublishError(f"Source release metadata is invalid: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("app_name") != "EOAT Atlas":
        raise PublishError("Source release_metadata.json is not EOAT Atlas metadata")
    Version.parse(str(payload.get("app_version", "")))
    return payload


def _target_metadata(original: dict[str, Any], version: Version) -> dict[str, Any]:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    completed = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False)
    commit = (os.getenv("GITHUB_SHA") or completed.stdout.strip()) if completed.returncode == 0 else ""
    if not commit:
        raise PublishError("Exact source commit is unavailable; publication is blocked.")
    result = dict(original)
    result.update({
        "app_version": str(version),
        "release_id": f"eoat-atlas-{version}",
        "build_id": build_identifier(version, commit, now),
        "build_date": now.date().isoformat(),
        "build_timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "git_commit": commit,
        "release_channel": "production",
        "environment": "production",
    })
    return result


def _write_source_metadata(payload: dict[str, Any]) -> None:
    path = ROOT / "release_metadata.json"
    temp = path.with_suffix(".json.release-temp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)


@contextmanager
def staged_source_metadata(payload: dict[str, Any]) -> Iterator[None]:
    path = ROOT / "release_metadata.json"
    original = path.read_bytes()
    try:
        _write_source_metadata(payload)
        yield
    finally:
        path.write_bytes(original)


def _run(name: str, command: list[str], results: dict[str, Any], *, cwd: Path = ROOT, env: dict[str, str] | None = None) -> None:
    print(f"\n[{name}] {' '.join(command)}")
    started = time.monotonic()
    completed = subprocess.run(command, cwd=cwd, text=True, env=env)
    results[name] = {"command": command, "exit_code": completed.returncode, "elapsed_seconds": round(time.monotonic() - started, 2)}
    if completed.returncode:
        raise PublishError(f"{name} failed with exit code {completed.returncode}")


def _validate_build(app_dir: Path, target: Version) -> None:
    exe = app_dir / "EOAT Atlas.exe"
    metadata_path = app_dir / "release_metadata.json"
    if not exe.is_file() or exe.stat().st_size <= 0:
        raise PublishError(f"Built executable is missing or empty: {exe}")
    candidates = [metadata_path, app_dir / "_internal" / "release_metadata.json"]
    metadata_path = next((path for path in candidates if path.is_file()), metadata_path)
    if not metadata_path.is_file():
        raise PublishError("Built release_metadata.json is missing")
    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    if payload.get("app_version") != str(target):
        raise PublishError("Built metadata version does not equal the proposed version")
    if any((app_dir / name).exists() for name in ("settings.json", "install_identity.json", "local_cache.db")):
        raise PublishError("Mutable runtime data was included in the build")


def _create_package(app_dir: Path, package: Path) -> None:
    with zipfile.ZipFile(package, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(app_dir.rglob("*")):
            if path.is_file():
                archive.write(path, Path("EOAT Atlas") / path.relative_to(app_dir))


def _validate_package(package: Path, target: Version) -> None:
    with tempfile.TemporaryDirectory(prefix="eoat_package_verify_") as temp:
        with zipfile.ZipFile(package) as archive:
            archive.extractall(temp)
        _validate_build(Path(temp) / "EOAT Atlas", target)


def _deployment_layout(root: Path) -> None:
    for relative in ("Packages/Current", "Packages/Archive", "Manifests", "Logs/Deployment Tests"):
        (root / relative).mkdir(parents=True, exist_ok=True)


def _publish_package(root: Path, local_package: Path, manifest: dict[str, Any], previous: dict[str, Any] | None) -> None:
    _deployment_layout(root)
    current = root / "Packages" / "Current"
    archive = root / "Packages" / "Archive"
    manifests = root / "Manifests"
    final = current / local_package.name
    staged = current / f"{local_package.name}.staging-{uuid.uuid4().hex}"
    moved_previous: tuple[Path, Path] | None = None
    created_final = False
    try:
        if final.exists():
            if final.stat().st_size != local_package.stat().st_size or sha256_file(final) != sha256_file(local_package):
                raise PublishError(f"Immutable release already exists with different content: {final}")
        else:
            shutil.copy2(local_package, staged)
            if staged.stat().st_size != local_package.stat().st_size or sha256_file(staged) != sha256_file(local_package):
                raise PublishError("Network staging verification failed")
            _validate_package(staged, Version.parse(manifest["latest_version"]))
            staged.replace(final)
            created_final = True
        if previous:
            previous_path = Path(previous["release_path"])
            if previous_path.exists() and previous_path.parent.resolve() == current.resolve() and previous_path != final:
                archived = archive / previous_path.name
                if archived.exists():
                    raise PublishError(f"Previous package archive target already exists: {archived}")
                previous_path.replace(archived)
                moved_previous = (archived, previous_path)
            previous_manifest = manifests / f"latest_v{previous['latest_version']}.json"
            if not previous_manifest.exists():
                previous_manifest.write_text(json.dumps(previous, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        manifest["release_path"] = str(final)
        validate_manifest(manifest, require_package=True)
        atomic_write_json(manifests / "latest.json", manifest)
        read_manifest(manifests / "latest.json", require_package=True)
    except Exception:
        staged.unlink(missing_ok=True)
        if moved_previous and moved_previous[0].exists() and not moved_previous[1].exists():
            moved_previous[0].replace(moved_previous[1])
        if created_final:
            final.unlink(missing_ok=True)
        raise


def _write_log(root: Path, record: dict[str, Any], *, production_mutation: bool) -> Path:
    log_root = root / "Logs" / "Deployment Tests" if production_mutation else ROOT / "build" / "release_logs"
    log_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = log_root / f"publish_{stamp}.json"
    json_path.write_text(json.dumps(record, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    md_path = log_root / f"publish_{stamp}.md"
    md_path.write_text("# EOAT Atlas deployment result\n\n" + "\n".join(f"- {key}: {value}" for key, value in record.items() if key != "checks") + "\n", encoding="utf-8")
    return json_path


def publish(args: argparse.Namespace) -> int:
    started = time.monotonic()
    stage = "version-state"
    results: dict[str, Any] = {}
    source_original: dict[str, Any] | None = None
    target_metadata: dict[str, Any] | None = None
    previous: dict[str, Any] | None = None
    target: Version | None = None
    production_mutation = not args.dry_run
    log_root = args.deployment_root
    lock: ReleaseLock | None = None
    try:
        source_original = _read_source_metadata()
        source_version = Version.parse(source_original["app_version"])
        manifest_path = args.deployment_root / "Manifests" / "latest.json"
        if manifest_path.exists():
            previous = read_manifest(manifest_path, require_package=True)
            published = Version.parse(previous["latest_version"])
            if source_version <= published:
                raise PublishError(
                    f"Canonical source version {source_version} must be newer than published version {published}; "
                    "complete the task version bump before publishing"
                )
            target = source_version
        elif not args.initialize:
            raise PublishError("No valid production latest.json exists. Re-run with --initialize for the deliberate initial release.")
        else:
            target = source_version
        minimum = Version.parse(args.minimum_supported_version) if args.minimum_supported_version else Version.parse(previous["minimum_supported_version"] if previous else "0.1.0")
        if minimum > target:
            raise PublishError("minimum_supported_version cannot be newer than the target release")
        target_metadata = _target_metadata(source_original, target)
        print("\nEOAT Atlas Release\n")
        print(f"Current published version: {previous['latest_version'] if previous else 'NONE (initialization)'}")
        print(f"Proposed version:          {target}")
        print(f"Deployment root:           {args.deployment_root}")
        print(f"Release notes:             {args.release_notes or '(none)'}")
        print(f"Mode:                      {'DRY RUN' if args.dry_run else 'LIVE PUBLISH'}")
        if not args.yes:
            expected = "PUBLISH" if not args.dry_run else "DRY RUN"
            if input(f"\nType {expected} to continue: ").strip() != expected:
                raise PublishError("Release cancelled; confirmation did not match")

        working_deployment = args.deployment_root
        simulation: tempfile.TemporaryDirectory[str] | None = None
        if args.dry_run:
            simulation = tempfile.TemporaryDirectory(prefix="eoat_publish_dry_run_")
            working_deployment = Path(simulation.name) / "EOAT Atlas"
            _deployment_layout(working_deployment)
            if previous:
                old_copy = working_deployment / "Packages" / "Current" / Path(previous["release_path"]).name
                shutil.copy2(previous["release_path"], old_copy)
                simulated_previous = dict(previous, release_path=str(old_copy))
                atomic_write_json(working_deployment / "Manifests" / "latest.json", simulated_previous)
                previous = simulated_previous
        else:
            lock = ReleaseLock(args.deployment_root)
            lock.acquire()

        with tempfile.TemporaryDirectory(prefix="eoat_release_build_") as temp:
            work = Path(temp)
            dist = work / "dist"
            package = work / f"EOAT-Atlas_v{target}.zip"
            stage = "preflight"
            _run("preflight", [sys.executable, "scripts/preflight_onedir_readiness.py"], results)
            stage = "tests"
            _run("tests", [sys.executable, "-m", "pytest", "-q", "tests/test_release_system.py"], results)
            metadata_override = work / "release_metadata.json"
            metadata_override.write_text(json.dumps(target_metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            build_env = os.environ.copy()
            build_env["EOAT_ATLAS_BUILD_METADATA"] = str(metadata_override)
            stage = "build"
            _run("build", [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--distpath", str(dist), "--workpath", str(work / "pyinstaller"), str(ROOT / "EOAT_Atlas.spec")], results, env=build_env)
            app_dir = dist / "EOAT Atlas"
            stage = "build-validation"
            _validate_build(app_dir, target)
            stage = "smoke-test"
            _run("smoke_test", [sys.executable, "scripts/smoke_test_package.py", str(app_dir / "EOAT Atlas.exe")], results)
            stage = "package"
            _create_package(app_dir, package)
            _validate_package(package, target)
            manifest = {
                "latest_version": str(target),
                "release_id": target_metadata["release_id"],
                "build_id": target_metadata["build_id"],
                "release_path": str(working_deployment / "Packages" / "Current" / package.name),
                "minimum_supported_version": str(minimum),
                "sha256": sha256_file(package),
                "package_size": package.stat().st_size,
                "published_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "release_notes": args.release_notes,
                "manifest_schema_version": 2,
            }
            stage = "network-promotion"
            _publish_package(working_deployment, package, manifest, previous)
            if args.dry_run:
                read_manifest(working_deployment / "Manifests" / "latest.json", require_package=True)
                print("Dry-run transaction validated in an isolated temporary deployment root.")
            elif not args.preserve_source_metadata:
                stage = "source-version-commit"
                _write_source_metadata(target_metadata)
        record = {"status": "success", "dry_run": args.dry_run, "source_version": source_original["app_version"], "previous_version": previous["latest_version"] if previous else None, "target_version": str(target), "deployment_root": str(args.deployment_root), "release_notes": args.release_notes, "checks": results, "manifest_promoted": not args.dry_run, "elapsed_seconds": round(time.monotonic() - started, 2), "developer": getpass.getuser(), "machine": socket.gethostname(), "timestamp": datetime.now().astimezone().isoformat(timespec="seconds")}
        log = _write_log(log_root, record, production_mutation=production_mutation)
        print(f"\nSUCCESS: EOAT Atlas v{target} {'dry-run validated' if args.dry_run else 'published'}.")
        print(f"Deployment log: {log}")
        return 0
    except Exception as exc:
        record = {"status": "failure", "failed_stage": stage, "error": f"{type(exc).__name__}: {exc}", "dry_run": args.dry_run, "source_version": source_original.get("app_version") if source_original else None, "target_version": str(target) if target else None, "deployment_root": str(args.deployment_root), "release_notes": args.release_notes, "checks": results, "manifest_promoted": False, "elapsed_seconds": round(time.monotonic() - started, 2), "timestamp": datetime.now().astimezone().isoformat(timespec="seconds")}
        try:
            log = _write_log(log_root, record, production_mutation=production_mutation)
        except Exception:
            log = None
        print(f"\nFAILED at {stage}: {exc}", file=sys.stderr)
        if log:
            print(f"Failure log: {log}", file=sys.stderr)
        return 1
    finally:
        if lock:
            lock.release()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build, validate, and transactionally publish EOAT Atlas")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--deployment-root", type=Path, default=DEFAULT_DEPLOYMENT_ROOT)
    parser.add_argument("--release-notes", default="")
    parser.add_argument("--minimum-supported-version")
    parser.add_argument("--initialize", action="store_true")
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--preserve-source-metadata", action="store_true", help="For temporary integration deployments only; never use for a live release")
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(publish(parse_args()))
