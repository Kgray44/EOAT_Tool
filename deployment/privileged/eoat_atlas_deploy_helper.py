#!/usr/bin/env python3
"""Narrow root deployment helper for EOAT Atlas.

The helper deliberately accepts structured requests only.  It never executes a
request-provided command, path, environment file, or systemd unit.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ID = re.compile(r"^[a-z0-9][a-z0-9-]{7,63}$")
SHA = re.compile(r"^[0-9a-f]{64}$")
COMMIT = re.compile(r"^[0-9a-f]{40}$")
VERSION = re.compile(r"^\d+\.\d+\.\d+$")
SAFE_FILE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,180}$")
SERVICE = "eoat-atlas.service"
STATES = {
    "CREATED",
    "PREFLIGHT_PASSED",
    "LOCK_ACQUIRED",
    "BACKUP_CREATED",
    "ARTIFACT_TRANSFERRED",
    "ARTIFACT_VERIFIED",
    "RELEASE_EXTRACTED",
    "RUNTIME_READY",
    "STAGED_VALIDATED",
    "MIGRATION_APPROVED",
    "MIGRATION_COMPLETE",
    "ACTIVATION_STARTED",
    "ACTIVATED",
    "SERVICE_RESTARTED",
    "HEALTH_VALIDATED",
    "COMPLETED",
    "ROLLBACK_STARTED",
    "ROLLED_BACK",
    "FAILED",
    "MANUAL_INTERVENTION_REQUIRED",
}


def utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as stream:
        temp = Path(stream.name)
        json.dump(value, stream, sort_keys=True, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


@dataclass(frozen=True)
class Paths:
    root: Path = Path("/opt/eoat-atlas")
    lock: Path = Path("/var/lock/eoat-atlas-deploy.lock")
    runtime_env: Path = Path("/etc/eoat-atlas/runtime.env")

    @property
    def incoming(self) -> Path:
        return self.root / "incoming"

    @property
    def releases(self) -> Path:
        return self.root / "releases"

    @property
    def shared(self) -> Path:
        return self.root / "shared"

    @property
    def transactions(self) -> Path:
        return self.shared / "deployment-transactions"

    @property
    def receipts(self) -> Path:
        return self.shared / "deployment-receipts"

    @property
    def backups(self) -> Path:
        return self.shared / "backups"

    @property
    def current(self) -> Path:
        return self.root / "current"

    @property
    def previous(self) -> Path:
        return self.root / "previous"


class Rejected(RuntimeError):
    pass


class Helper:
    def __init__(
        self, paths: Paths | None = None, runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run
    ):
        self.paths, self.runner = paths or Paths(), runner

    def _state_path(self, deployment_id: str) -> Path:
        self._id(deployment_id)
        return self.paths.transactions / f"{deployment_id}.json"

    @staticmethod
    def _id(value: object) -> str:
        if not isinstance(value, str) or not ID.fullmatch(value):
            raise Rejected("invalid deployment_id")
        return value

    @staticmethod
    def _field(request: dict[str, Any], name: str, pattern: re.Pattern[str]) -> str:
        value = request.get(name)
        if not isinstance(value, str) or not pattern.fullmatch(value):
            raise Rejected(f"invalid {name}")
        return value

    def _load(self, deployment_id: str) -> dict[str, Any]:
        path = self._state_path(deployment_id)
        if not path.is_file():
            raise Rejected("unknown deployment_id")
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise Rejected("invalid transaction state")
        return value

    def _save(self, state: dict[str, Any], status: str, **extra: Any) -> dict[str, Any]:
        if status not in STATES:
            raise Rejected("invalid transaction state")
        state.update(extra)
        state["state"] = status
        state["updated_at_utc"] = utc()
        state.setdefault("events", []).append({"state": status, "at_utc": state["updated_at_utc"]})
        atomic_json(self._state_path(state["deployment_id"]), state)
        # Keep the lock useful for an interrupted-deployment investigation.  It
        # deliberately contains only the transaction metadata, never request
        # credentials or environment contents.
        if self.paths.lock.is_file():
            try:
                locked = json.loads(self.paths.lock.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise Rejected("deployment lock is malformed") from exc
            if locked.get("deployment_id") == state["deployment_id"]:
                atomic_json(
                    self.paths.lock,
                    {
                        "deployment_id": state["deployment_id"],
                        "state": status,
                        "updated_at_utc": state["updated_at_utc"],
                        "previous_target": state.get("previous_target"),
                    },
                )
        return state

    def _lock(self, state: dict[str, Any]) -> None:
        self.paths.lock.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(self.paths.lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640)
        except FileExistsError as exc:
            existing = json.loads(self.paths.lock.read_text(encoding="utf-8"))
            raise Rejected(f"deployment lock is held by {existing.get('deployment_id', 'unknown')}") from exc
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(state, stream, sort_keys=True)

    def _assert_lock(self, deployment_id: str) -> None:
        if not self.paths.lock.is_file():
            raise Rejected("deployment lock is absent")
        value = json.loads(self.paths.lock.read_text(encoding="utf-8"))
        if value.get("deployment_id") != deployment_id:
            raise Rejected("deployment lock belongs to another transaction")

    def _release_lock(self, deployment_id: str) -> None:
        self._assert_lock(deployment_id)
        self.paths.lock.unlink()

    def _receipt(self, state: dict[str, Any]) -> None:
        atomic_json(self.paths.receipts / f"{state['deployment_id']}.json", state)

    def _current_target(self) -> str:
        if not self.paths.current.is_symlink():
            raise Rejected("current release symlink is absent")
        return str(self.paths.current.resolve(strict=True))

    def _safe_archive(self, archive: Path) -> None:
        if not tarfile.is_tarfile(archive):
            raise Rejected("artifact is not a tar archive")
        with tarfile.open(archive, "r:gz") as bundle:
            for member in bundle.getmembers():
                name = Path(member.name)
                if (
                    name.is_absolute()
                    or ".." in name.parts
                    or member.isdev()
                    or member.isfifo()
                    or member.issym()
                    or member.islnk()
                ):
                    raise Rejected(f"unsafe archive member: {member.name}")

    @staticmethod
    def _json(path: Path, label: str) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise Rejected(f"invalid {label}") from exc
        if not isinstance(value, dict):
            raise Rejected(f"invalid {label}")
        return value

    def _validate_manifest(self, state: dict[str, Any], staging: Path) -> None:
        """Bind the archive to its signed-off release identity before activation."""
        manifest = self._json(staging / "release_manifest.json", "embedded release manifest")
        if manifest != state.get("manifest_core"):
            raise Rejected("embedded manifest does not exactly match external manifest core")
        fields = {"version": state["version"], "commit_sha": state["commit_sha"]}
        for name, expected in fields.items():
            if manifest.get(name) != expected:
                raise Rejected(f"embedded manifest {name} does not match transaction")
        release_id = manifest.get("release_id")
        build_id = manifest.get("build_id")
        if not isinstance(release_id, str) or not release_id or not isinstance(build_id, str) or not build_id:
            raise Rejected("embedded manifest has no release/build identity")
        state["release_id"], state["build_id"] = release_id, build_id

    def _run(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        result = self.runner(command, text=True, capture_output=True, check=False)
        if result.returncode:
            raise Rejected(f"approved command failed: {command[0]}")
        return result

    def _validate_health(self, state: dict[str, Any], *, target_release: bool) -> None:
        result = self._run(
            ["/usr/bin/curl", "--fail", "--silent", "--max-time", "10", "http://127.0.0.1:8765/api/v1/health"]
        )
        try:
            health = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise Rejected("health endpoint did not return JSON") from exc
        if not isinstance(health, dict):
            raise Rejected("health endpoint returned an invalid document")
        required = {
            "api_reachable": True,
            "database_reachable": True,
            "compatible": True,
            "environment": "production",
            "writes_enabled": False,
        }
        for field, expected in required.items():
            if health.get(field) != expected:
                raise Rejected(f"health metadata {field} is not {expected!r}")
        if health.get("current_schema_revision") != health.get("expected_schema_revision"):
            raise Rejected("health metadata reports an incompatible schema revision")
        if target_release:
            expected_identity = {
                "application_version": state["version"],
                "release_id": state["release_id"],
                "build_id": state["build_id"],
            }
            for field, expected in expected_identity.items():
                if health.get(field) != expected:
                    raise Rejected(f"health metadata {field} does not match activated release")

    def begin(self, request: dict[str, Any]) -> dict[str, Any]:
        deployment_id = self._id(request.get("deployment_id"))
        if self._state_path(deployment_id).exists():
            raise Rejected("deployment_id already exists")
        version = self._field(request, "version", VERSION)
        commit = self._field(request, "commit_sha", COMMIT)
        artifact = self._field(request, "artifact_filename", SAFE_FILE)
        sha = self._field(request, "artifact_sha256", SHA)
        external_manifest_sha = self._field(request, "external_manifest_sha256", SHA)
        if not artifact.endswith(".tar.gz") or version not in artifact or commit[:7] not in artifact:
            raise Rejected("artifact identity is unsafe")
        current = self._current_target()
        try:
            executor = os.getlogin()
        except OSError:
            executor = f"uid:{os.getuid()}"
        state = {
            "schema_version": 1,
            "deployment_id": deployment_id,
            "version": version,
            "commit_sha": commit,
            "artifact_filename": artifact,
            "artifact_sha256": sha,
            "external_manifest_sha256": external_manifest_sha,
            "migration_decision": request.get("migration_decision"),
            "previous_target": current,
            "created_at_utc": utc(),
            "executor": executor,
            "events": [],
        }
        self._save(state, "CREATED")
        self._save(state, "PREFLIGHT_PASSED", preflight="client-side verified release and server inspection")
        self._lock(state)
        return self._save(state, "LOCK_ACQUIRED")

    def stage(self, request: dict[str, Any]) -> dict[str, Any]:
        state = self._load(self._id(request.get("deployment_id")))
        self._assert_lock(state["deployment_id"])
        if state["state"] != "LOCK_ACQUIRED":
            raise Rejected("transaction is not ready for staging")
        if state.get("migration_decision") != "NOT_REQUIRED":
            raise Rejected("migration-bearing deployments require explicit approved migration flow")
        self._save(
            state,
            "BACKUP_CREATED",
            backup={"database": "NOT_REQUIRED", "reason": "current revision equals target revision"},
        )
        source = self.paths.incoming / f".{state['deployment_id']}.{state['artifact_filename']}"
        external_path = self.paths.incoming / f".{state['deployment_id']}.release_manifest.json"
        checksum_path = self.paths.incoming / f".{state['deployment_id']}.{state['artifact_filename']}.sha256"
        if not source.is_file() or digest(source) != state["artifact_sha256"]:
            raise Rejected("staged artifact hash does not match request")
        if not external_path.is_file() or digest(external_path) != state["external_manifest_sha256"]:
            raise Rejected("staged external manifest hash does not match request")
        external = self._json(external_path, "external release manifest")
        core, artifact = external.get("manifest_core"), external.get("artifact")
        if not isinstance(core, dict) or not isinstance(artifact, dict):
            raise Rejected("external release manifest has invalid shape")
        if artifact.get("filename") != state["artifact_filename"] or artifact.get("sha256") != state["artifact_sha256"]:
            raise Rejected("external release manifest artifact does not match transaction")
        if artifact.get("size_bytes") != source.stat().st_size:
            raise Rejected("external release manifest size does not match transaction")
        if core.get("version") != state["version"] or core.get("commit_sha") != state["commit_sha"]:
            raise Rejected("external release manifest identity does not match transaction")
        if external.get("embedded_manifest_sha256") != hashlib.sha256(canonical_json(core)).hexdigest():
            raise Rejected("external release manifest embedded digest is invalid")
        if not checksum_path.is_file():
            raise Rejected("staged checksum file is absent")
        checksum = checksum_path.read_text(encoding="utf-8").strip().split()
        if (
            len(checksum) != 2
            or checksum[0] != state["artifact_sha256"]
            or checksum[1].lstrip("*") != state["artifact_filename"]
        ):
            raise Rejected("staged checksum file does not match transaction")
        state["manifest_core"] = core
        self._save(state, "ARTIFACT_TRANSFERRED")
        self._save(state, "ARTIFACT_VERIFIED", server_sha256=state["artifact_sha256"])
        self._safe_archive(source)
        target = self.paths.releases / f"eoat-atlas-server-{state['version']}-{state['commit_sha'][:7]}"
        staging = self.paths.releases / f".staging-{state['deployment_id']}"
        if target.exists() or staging.exists():
            raise Rejected("target or staging release directory already exists")
        staging.mkdir(parents=True, mode=0o750)
        with tarfile.open(source, "r:gz") as bundle:
            bundle.extractall(staging, filter="data")
        required = (
            staging / "release_manifest.json",
            staging / "server" / "eoat_api" / "app.py",
            staging / "requirements.lock",
        )
        if not all(path.is_file() for path in required):
            raise Rejected("staged release misses required runtime files")
        self._validate_manifest(state, staging)
        self._save(state, "RELEASE_EXTRACTED", staging_path=str(staging), target_path=str(target))
        self._run(["/usr/bin/python3", "-m", "venv", str(staging / "venv")])
        pip = staging / "venv" / "bin" / "pip"
        self._run([str(pip), "install", "--require-hashes", "-r", str(staging / "requirements.lock")])
        self._save(state, "RUNTIME_READY")
        self._run([str(staging / "venv" / "bin" / "python"), "-c", "import server.eoat_api.app"])
        # Ownership is fixed here; no user supplied account or group can reach
        # this command.  It happens only after archive and manifest validation.
        self._run(["/usr/bin/chown", "-R", "eoat-atlas:eoat-atlas", str(staging)])
        os.replace(staging, target)
        self._save(state, "STAGED_VALIDATED", target_path=str(target))
        return state

    def _replace_link(self, link: Path, target: Path, deployment_id: str) -> None:
        releases_root = self.paths.releases.resolve()
        if not target.is_dir() or target.resolve().parent != releases_root:
            raise Rejected("unsafe symlink target")
        temp = link.with_name(f".{link.name}-{deployment_id}")
        temp.unlink(missing_ok=True)
        temp.symlink_to(target)
        os.replace(temp, link)

    def activate(self, request: dict[str, Any]) -> dict[str, Any]:
        state = self._load(self._id(request.get("deployment_id")))
        self._assert_lock(state["deployment_id"])
        if state["state"] != "STAGED_VALIDATED":
            raise Rejected("transaction is not staged")
        old = self._current_target()
        if old != state["previous_target"]:
            raise Rejected("current release changed since staging")
        target = Path(state["target_path"])
        self._save(state, "ACTIVATION_STARTED")
        self._replace_link(self.paths.previous, Path(old), state["deployment_id"])
        self._replace_link(self.paths.current, target, state["deployment_id"])
        if self._current_target() != str(target.resolve()):
            self._replace_link(self.paths.current, Path(old), state["deployment_id"])
            raise Rejected("current symlink verification failed")
        self._save(state, "ACTIVATED", current_target=str(target), previous_target=old)
        self._run(["/bin/systemctl", "restart", SERVICE])
        self._run(["/bin/systemctl", "is-active", "--quiet", SERVICE])
        self._save(state, "SERVICE_RESTARTED")
        try:
            self._validate_health(state, target_release=True)
        except Rejected:
            self._save(state, "ROLLBACK_STARTED", failure="post-activation health failed")
            self._replace_link(self.paths.current, Path(old), state["deployment_id"])
            try:
                self._run(["/bin/systemctl", "restart", SERVICE])
                self._run(["/bin/systemctl", "is-active", "--quiet", SERVICE])
                self._validate_health(state, target_release=False)
            except Rejected as exc:
                self._save(state, "MANUAL_INTERVENTION_REQUIRED", recovery_failure=str(exc))
                self._receipt(state)
                raise Rejected("rollback health validation failed; manual intervention is required") from exc
            self._save(state, "ROLLED_BACK", rolled_back_at_utc=utc())
            self._receipt(state)
            self._release_lock(state["deployment_id"])
            return state
        self._save(state, "HEALTH_VALIDATED")
        self._save(state, "COMPLETED", completed_at_utc=utc())
        self._receipt(state)
        self._release_lock(state["deployment_id"])
        return state

    def status(self, request: dict[str, Any]) -> dict[str, Any]:
        return self._load(self._id(request.get("deployment_id")))

    def abort(self, request: dict[str, Any]) -> dict[str, Any]:
        state = self._load(self._id(request.get("deployment_id")))
        self._assert_lock(state["deployment_id"])
        if state["state"] not in {
            "CREATED",
            "LOCK_ACQUIRED",
            "BACKUP_CREATED",
            "ARTIFACT_VERIFIED",
            "RELEASE_EXTRACTED",
            "RUNTIME_READY",
            "STAGED_VALIDATED",
        }:
            raise Rejected("active or completed deployment cannot be aborted")
        staging = self.paths.releases / f".staging-{state['deployment_id']}"
        shutil.rmtree(staging, ignore_errors=True)
        self._save(state, "FAILED", aborted=True)
        self._receipt(state)
        self._release_lock(state["deployment_id"])
        return state

    def rollback(self, request: dict[str, Any]) -> dict[str, Any]:
        """Explicitly restore the known previous release for an activated transaction."""
        state = self._load(self._id(request.get("deployment_id")))
        self._assert_lock(state["deployment_id"])
        if state["state"] not in {
            "ACTIVATION_STARTED",
            "ACTIVATED",
            "SERVICE_RESTARTED",
            "HEALTH_VALIDATED",
            "MANUAL_INTERVENTION_REQUIRED",
        }:
            raise Rejected("transaction is not eligible for explicit rollback")
        old = Path(state["previous_target"])
        self._save(state, "ROLLBACK_STARTED", requested_by="explicit-helper-operation")
        self._replace_link(self.paths.current, old, state["deployment_id"])
        try:
            self._run(["/bin/systemctl", "restart", SERVICE])
            self._run(["/bin/systemctl", "is-active", "--quiet", SERVICE])
            self._validate_health(state, target_release=False)
        except Rejected as exc:
            self._save(state, "MANUAL_INTERVENTION_REQUIRED", recovery_failure=str(exc))
            self._receipt(state)
            raise Rejected("explicit rollback could not restore healthy service") from exc
        self._save(state, "ROLLED_BACK", rolled_back_at_utc=utc())
        self._receipt(state)
        self._release_lock(state["deployment_id"])
        return state

    def recover(self, request: dict[str, Any]) -> dict[str, Any]:
        """Report, but never guess at, interrupted deployment recovery actions."""
        state = self._load(self._id(request.get("deployment_id")))
        self._assert_lock(state["deployment_id"])
        state["recovery"] = {
            "lock_present": True,
            "current_target": self._current_target(),
            "previous_target": state.get("previous_target"),
            "required_action": "abort"
            if state["state"]
            in {
                "CREATED",
                "LOCK_ACQUIRED",
                "BACKUP_CREATED",
                "ARTIFACT_VERIFIED",
                "RELEASE_EXTRACTED",
                "RUNTIME_READY",
                "STAGED_VALIDATED",
            }
            else "rollback",
        }
        return state

    def retention_status(self, _request: dict[str, Any]) -> dict[str, Any]:
        protected = {self._current_target(), str(self.paths.previous.resolve()) if self.paths.previous.exists() else ""}
        return {
            "current": self._current_target(),
            "previous": protected - {self._current_target()},
            "eligible": sorted(
                str(p)
                for p in self.paths.releases.iterdir()
                if p.is_dir() and str(p.resolve()) not in protected and not p.name.startswith(".")
            ),
        }

    def dispatch(self, request: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(request, dict) or set(request) - {
            "operation",
            "deployment_id",
            "version",
            "commit_sha",
            "artifact_filename",
            "artifact_sha256",
            "external_manifest_sha256",
            "migration_decision",
        }:
            raise Rejected("unknown request fields")
        operation = request.get("operation")
        methods = {
            "begin": self.begin,
            "stage": self.stage,
            "activate": self.activate,
            "status": self.status,
            "abort": self.abort,
            "rollback": self.rollback,
            "recover": self.recover,
            "retention-status": self.retention_status,
        }
        if operation not in methods:
            raise Rejected("unsupported privileged operation")
        return methods[operation](request)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="EOAT Atlas narrowly scoped deployment helper")
    parser.add_argument("--request-b64", required=True)
    args = parser.parse_args(argv)
    try:
        if os.geteuid() != 0:
            raise Rejected("helper must run as root")
        raw = base64.b64decode(args.request_b64.encode("ascii"), validate=True)
        if len(raw) > 16384:
            raise Rejected("request is too large")
        result = Helper().dispatch(json.loads(raw.decode("utf-8")))
        print(json.dumps(result, sort_keys=True))
        return 0
    except (Rejected, ValueError, UnicodeError, json.JSONDecodeError) as exc:
        print(f"REJECTED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
