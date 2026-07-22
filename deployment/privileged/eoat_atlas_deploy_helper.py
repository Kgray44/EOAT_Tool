#!/usr/bin/env python3
"""Narrow root deployment helper for EOAT Atlas.

The helper deliberately accepts structured requests only.  It never executes a
request-provided command, path, environment file, or systemd unit.
"""

from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import json
import os
import re
import shlex
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
SERVICE_ACCOUNT = "eoat-atlas"
HELPER_POLICY_VERSION = 1
HELPER_IMPLEMENTATION_COMMIT = "$Format:%H$"
STAGED_RUNTIME_VALIDATION = r'''
# EOAT_STAGE_RUNTIME_VALIDATION
import json
import socket
import threading
import time
import urllib.request

import uvicorn

listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
listener.bind(("127.0.0.1", 0))
listener.listen(5)
port = listener.getsockname()[1]
server = uvicorn.Server(uvicorn.Config("server.eoat_api.app:app", log_level="warning", lifespan="on"))
thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
thread.start()
try:
    deadline = time.monotonic() + 20
    while not server.started and thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.05)
    if not server.started:
        raise RuntimeError("staged API did not start")
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/v1/health", timeout=10) as response:
        health = json.loads(response.read().decode("utf-8"))
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/v1/version", timeout=10) as response:
        version = json.loads(response.read().decode("utf-8"))
    print(json.dumps({"health": health, "version": version}, sort_keys=True))
finally:
    server.should_exit = True
    thread.join(timeout=10)
    listener.close()
'''
STATES = {
    "CREATED",
    "PACKAGE_VERIFIED",
    "PREFLIGHT_PASSED",
    "LOCK_ACQUIRED",
    "BACKUP_STARTED",
    "BACKUP_CREATED",
    "BACKUP_VERIFIED",
    "ARTIFACT_TRANSFERRED",
    "ARTIFACT_VERIFIED",
    "RELEASE_EXTRACTED",
    "RUNTIME_READY",
    "STAGED_VALIDATED",
    "MIGRATION_PREFLIGHT_PASSED",
    "MIGRATION_APPROVED",
    "MIGRATION_STARTED",
    "MIGRATION_COMPLETE",
    "MIGRATION_VERIFIED",
    "ACTIVATION_STARTED",
    "ACTIVATED",
    "SERVICE_RESTARTED",
    "HEALTH_VALIDATED",
    "POSTCHECK_PASSED",
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
    migration_env: Path = Path("/etc/eoat-atlas/migration.env")
    proc: Path = Path("/proc")

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

    def _migration_environment(self) -> dict[str, str]:
        """Read the fixed root-only migration environment without logging it.

        Values are never accepted from a request and never copied into a
        receipt.  The administrator owns this protected file; the helper only
        consumes it for its fixed mysqldump/mysql/Alembic commands.
        """
        path = self.paths.migration_env
        try:
            stat = path.stat()
            if os.name != "nt" and (stat.st_uid != 0 or stat.st_mode & 0o077):
                raise Rejected("migration environment ownership or permissions are unsafe")
            raw = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise Rejected("protected migration environment is unavailable") from exc
        values: dict[str, str] = {}
        for line in raw.splitlines():
            if not line or line.lstrip().startswith("#"):
                continue
            if "=" not in line:
                raise Rejected("protected migration environment is malformed")
            key, value = line.split("=", 1)
            if not re.fullmatch(r"[A-Z][A-Z0-9_]{1,80}", key) or "\x00" in value:
                raise Rejected("protected migration environment is malformed")
            value = value.strip()
            if value.startswith(("'", '"')):
                try:
                    parsed = shlex.split(value, posix=True)
                except ValueError as exc:
                    raise Rejected("protected migration environment is malformed") from exc
                if len(parsed) != 1:
                    raise Rejected("protected migration environment is malformed")
                value = parsed[0]
            values[key] = value
        if values.get("EOAT_API_ENVIRONMENT", "production").casefold() != "production":
            raise Rejected("migration environment is not production")
        if values.get("EOAT_API_WRITES_ENABLED", "false").casefold() in {"1", "true", "yes", "on"}:
            raise Rejected("migration environment enables writes")
        # EOAT Atlas has always used the ``EOAT_DB_MIGRATION_*`` pair for
        # the privileged Alembic identity.  Earlier helper prototypes used
        # an alternate spelling, so accept that spelling only as a backwards
        # compatible alias.  Normalize it here, inside the root-only process,
        # rather than asking an operator to duplicate a credential in another
        # file or passing it through a request.
        user = (
            values.get("EOAT_DB_MIGRATION_USER")
            or values.get("EOAT_MIGRATION_DB_USER")
            or values.get("EOAT_DB_USER")
        )
        if not user or not re.fullmatch(r"[A-Za-z0-9_]{1,64}", user):
            raise Rejected("migration account is unavailable")
        if values.get("EOAT_DB_NAME") != self._database_name():
            raise Rejected("migration environment database is not the fixed production database")
        if values.get("EOAT_DB_HOST") != "127.0.0.1" or values.get("EOAT_DB_PORT") != "3306":
            raise Rejected("migration environment must use the fixed local MySQL endpoint")
        # Normalize the legacy user spelling only for the helper's fixed
        # child processes. Password material stays in the protected
        # environment until a mode-0600 defaults file is created for one
        # fixed MySQL client invocation.
        values["EOAT_MIGRATION_DB_USER"] = user
        # Do not inherit a caller-controlled environment into privileged
        # database or Alembic processes.  Absolute executable paths and the
        # fixed minimal environment below are sufficient for all approved
        # operations.
        return {
            "HOME": "/root",
            "LANG": "C.UTF-8",
            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            **values,
        }

    @staticmethod
    def _mysql_option_value(value: str) -> str:
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'

    def _mysql_defaults_file(self, environment: dict[str, str]) -> Path:
        """Create one root-only option file for a fixed local MySQL client."""
        password = (
            environment.get("EOAT_DB_MIGRATION_PASSWORD")
            or environment.get("EOAT_MIGRATION_DB_PASSWORD")
            or environment.get("EOAT_DB_PASSWORD")
        )
        if password is None:
            raise Rejected("migration account password is unavailable")
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=self.paths.migration_env.parent,
                prefix=".eoat-mysql-",
                delete=False,
            ) as stream:
                path = Path(stream.name)
                stream.write("[client]\n")
                stream.write(f"user={self._mysql_option_value(environment['EOAT_MIGRATION_DB_USER'])}\n")
                stream.write(f"password={self._mysql_option_value(password)}\n")
                stream.write(f"host={self._mysql_option_value(environment['EOAT_DB_HOST'])}\n")
                stream.write(f"port={self._mysql_option_value(environment['EOAT_DB_PORT'])}\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(path, 0o600)
            return path
        except OSError as exc:
            raise Rejected("secure MySQL defaults file is unavailable") from exc

    @staticmethod
    def _database_name() -> str:
        # This is deliberately not configurable through the request, manifest,
        # environment, or CLI.  The privileged helper exists only for EOAT
        # Atlas production.
        return "eoat_atlas_prod"

    def _migration_command(self, state: dict[str, Any], action: str) -> list[str]:
        staged = Path(str(state.get("target_path") or ""))
        binary = staged / "venv" / "bin" / "alembic"
        config = staged / "server" / "alembic.ini"
        if not binary.is_file() or not config.is_file() or staged.resolve().parent != self.paths.releases.resolve():
            raise Rejected("verified staged migration environment is unavailable")
        database = state["manifest_core"].get("database")
        if not isinstance(database, dict):
            raise Rejected("release metadata has no database contract")
        target = database.get("target_revision")
        predecessor = database.get("minimum_compatible_revision") or "20260717_0007"
        if not isinstance(target, str) or not re.fullmatch(r"[0-9]{8}_[0-9]{4}", target):
            raise Rejected("release target revision is unsafe")
        if not isinstance(predecessor, str) or not re.fullmatch(r"[0-9]{8}_[0-9]{4}", predecessor):
            raise Rejected("release predecessor revision is unsafe")
        if action == "current":
            return [str(binary), "-c", str(config), "current"]
        if action == "upgrade":
            return [str(binary), "-c", str(config), "upgrade", target]
        if action == "downgrade":
            return [str(binary), "-c", str(config), "downgrade", predecessor]
        raise Rejected("unsupported fixed migration action")

    def _alembic_revision(self, state: dict[str, Any]) -> str:
        result = self._run(
            self._migration_command(state, "current"),
            cwd=Path(state["target_path"]),
            env=self._migration_environment(),
            purpose="approved migration revision query",
        )
        matches = re.findall(r"\b[0-9]{8}_[0-9]{4}\b", result.stdout or "")
        if len(matches) != 1:
            raise Rejected("migration revision query returned an unexpected result")
        return matches[0]

    def _backup_path(self, state: dict[str, Any]) -> Path:
        identifier = state["deployment_id"]
        name = f"{identifier}-{self._database_name()}-pre-migration.sql.gz"
        path = self.paths.backups / name
        if path.exists() or path.is_symlink() or path.parent.resolve() != self.paths.backups.resolve():
            raise Rejected("production backup path is unsafe or already exists")
        return path

    def _create_backup(self, state: dict[str, Any]) -> dict[str, Any]:
        environment = self._migration_environment()
        target = self._backup_path(state)
        partial = target.with_suffix(".sql.partial")
        if partial.exists() or partial.is_symlink():
            raise Rejected("production backup partial path is unsafe")
        self._save(state, "BACKUP_STARTED")
        try:
            defaults = self._mysql_defaults_file(environment)
            try:
                # Prove that the fixed migration identity can reach only the
                # fixed production database before requesting a full backup.
                # This is deliberately a non-mutating query and uses the same
                # root-owned option file as mysqldump, so it cannot be
                # influenced by caller credentials or a database argument.
                self._run(
                    [
                        "/usr/bin/mysql",
                        f"--defaults-extra-file={defaults}",
                        "--batch",
                        "--skip-column-names",
                        "--execute",
                        "SELECT 1",
                        self._database_name(),
                    ],
                    env=environment,
                    purpose="approved migration database connection probe",
                )
                # mysqldump requires metadata privileges beyond a basic
                # connection.  Probe only the fixed production schema before
                # starting a potentially large dump so a missing metadata
                # privilege is reported safely and cannot leave a partial
                # backup mistaken for a recoverable artifact.
                self._run(
                    [
                        "/usr/bin/mysql",
                        f"--defaults-extra-file={defaults}",
                        "--batch",
                        "--skip-column-names",
                        "--execute",
                        "SHOW TABLES; SHOW EVENTS; SHOW TRIGGERS",
                        self._database_name(),
                    ],
                    env=environment,
                    purpose="approved backup metadata privilege probe",
                )
                result = self._run(
                    [
                        "/usr/bin/mysqldump",
                        f"--defaults-extra-file={defaults}",
                        "--single-transaction",
                        "--no-tablespaces",
                        "--routines",
                        "--events",
                        f"--result-file={partial}",
                        self._database_name(),
                    ],
                    env=environment,
                    purpose="approved production backup",
                )
            finally:
                defaults.unlink(missing_ok=True)
            # Test runners return a controlled stdout payload; real mysqldump
            # writes directly to the fixed partial file via --result-file.
            if not partial.exists() and result.stdout:
                partial.write_text(result.stdout, encoding="utf-8")
            if not partial.is_file() or partial.stat().st_size < 16:
                raise Rejected("production backup is empty or incomplete")
            with partial.open("rb") as source, gzip.open(target, "wb") as compressed:
                shutil.copyfileobj(source, compressed)
            os.chmod(target, 0o600)
            with gzip.open(target, "rb") as stream:
                sample = stream.read(4096)
            if not sample or b"\x00" in sample:
                raise Rejected("production backup is not structurally plausible")
            partial.unlink(missing_ok=True)
        except (OSError, Rejected) as exc:
            # A failed mysqldump can leave a partial file.  It belongs only to
            # this lock-bound deployment ID, so remove it before recording a
            # recoverable failed state; no migration or activation can follow.
            partial.unlink(missing_ok=True)
            failure = str(exc) if isinstance(exc, Rejected) else "production backup failed"
            self._save(state, "FAILED", failure=failure)
            self._receipt(state)
            raise
        record = {"id": target.stem, "path": str(target), "sha256": digest(target), "size_bytes": target.stat().st_size, "created_at_utc": utc()}
        return self._save(state, "BACKUP_CREATED", backup=record)

    def backup_production(self, request: dict[str, Any]) -> dict[str, Any]:
        state = self._load(self._id(request.get("deployment_id")))
        self._assert_lock(state["deployment_id"])
        if state.get("migration_decision") != "REQUIRED" or state["state"] != "LOCK_ACQUIRED":
            raise Rejected("migration backup is not permitted in the current transaction state")
        return self._create_backup(state)

    def verify_backup(self, request: dict[str, Any]) -> dict[str, Any]:
        state = self._load(self._id(request.get("deployment_id")))
        self._assert_lock(state["deployment_id"])
        if state["state"] != "BACKUP_CREATED" or not isinstance(state.get("backup"), dict):
            raise Rejected("migration backup has not been created")
        record = state["backup"]
        path = Path(str(record.get("path") or ""))
        if path.parent.resolve() != self.paths.backups.resolve() or path.is_symlink() or not path.is_file():
            raise Rejected("migration backup path is unsafe")
        backup_stat = path.stat()
        if (
            (os.name != "nt" and (backup_stat.st_uid != 0 or backup_stat.st_mode & 0o077))
            or backup_stat.st_size < 16
            or digest(path) != record.get("sha256")
        ):
            raise Rejected("migration backup verification failed")
        try:
            with gzip.open(path, "rb") as stream:
                if not stream.read(16):
                    raise Rejected("migration backup verification failed")
        except OSError as exc:
            raise Rejected("migration backup verification failed") from exc
        return self._save(state, "BACKUP_VERIFIED", backup_verified_at_utc=utc())

    def migration_preflight(self, request: dict[str, Any]) -> dict[str, Any]:
        state = self._load(self._id(request.get("deployment_id")))
        self._assert_lock(state["deployment_id"])
        if state.get("migration_decision") != "REQUIRED" or state["state"] != "STAGED_VALIDATED":
            raise Rejected("migration preflight is not permitted in the current transaction state")
        if not state.get("backup_verified_at_utc"):
            raise Rejected("migration preflight requires a verified backup")
        database = state["manifest_core"].get("database", {})
        predecessor = database.get("minimum_compatible_revision") or "20260717_0007"
        target = database.get("target_revision")
        current = self._alembic_revision(state)
        if current != predecessor or current == target:
            raise Rejected("production schema does not match the package predecessor revision")
        migration_files = list((Path(state["target_path"]) / "server" / "migrations" / "versions").glob(f"{target}_*.py"))
        if len(migration_files) != 1 or migration_files[0].is_symlink():
            raise Rejected("packaged migration file is missing or ambiguous")
        return self._save(
            state,
            "MIGRATION_PREFLIGHT_PASSED",
            migration_preflight={
                "current_revision": current,
                "target_revision": target,
                "writes_enabled": False,
                "migration_file": migration_files[0].name,
                "migration_sha256": digest(migration_files[0]),
            },
        )

    def apply_migration(self, request: dict[str, Any]) -> dict[str, Any]:
        state = self._load(self._id(request.get("deployment_id")))
        self._assert_lock(state["deployment_id"])
        if state["state"] != "MIGRATION_PREFLIGHT_PASSED":
            raise Rejected("migration apply requires a successful migration preflight")
        self._save(state, "MIGRATION_APPROVED")
        self._save(state, "MIGRATION_STARTED")
        try:
            self._run(self._migration_command(state, "upgrade"), cwd=Path(state["target_path"]), env=self._migration_environment(), purpose="approved production migration")
            target = state["manifest_core"]["database"]["target_revision"]
            if self._alembic_revision(state) != target:
                raise Rejected("approved migration did not reach the package target revision")
        except Rejected:
            self._save(state, "FAILED", failure="migration apply failed")
            self._receipt(state)
            raise
        return self._save(state, "MIGRATION_COMPLETE", migration_result={"target_revision": target, "exit_code": 0})

    def verify_migration(self, request: dict[str, Any]) -> dict[str, Any]:
        state = self._load(self._id(request.get("deployment_id")))
        self._assert_lock(state["deployment_id"])
        if state["state"] != "MIGRATION_COMPLETE":
            raise Rejected("migration verification requires a completed migration")
        target = state["manifest_core"]["database"]["target_revision"]
        if self._alembic_revision(state) != target or self._current_target() != state["previous_target"]:
            raise Rejected("migration verification failed")
        environment = self._migration_environment()
        defaults = self._mysql_defaults_file(environment)
        try:
            data_state = self._run(
                [
                    "/usr/bin/mysql",
                    f"--defaults-extra-file={defaults}",
                    "--batch",
                    "--skip-column-names",
                    "--execute=SELECT COUNT(*) FROM data_state",
                    self._database_name(),
                ],
                env=environment,
                purpose="fixed data-state singleton verification",
            ).stdout.strip()
        finally:
            defaults.unlink(missing_ok=True)
        if data_state != "1":
            raise Rejected("migration verification did not find exactly one data_state row")
        staged = self._validate_staged_runtime(state, Path(state["target_path"]))
        return self._save(state, "MIGRATION_VERIFIED", migration_verified_at_utc=utc(), staged_validation=staged)

    def cleanup_failed_deployment(self, request: dict[str, Any]) -> dict[str, Any]:
        state = self._load(self._id(request.get("deployment_id")))
        self._assert_lock(state["deployment_id"])
        if state["state"] not in {"FAILED", "ROLLED_BACK"} or self._current_target() != state["previous_target"]:
            raise Rejected("failed deployment cleanup is not permitted in the current transaction state")
        self._receipt(state)
        self._release_lock(state["deployment_id"])
        return state

    def downgrade_migration(self, request: dict[str, Any]) -> dict[str, Any]:
        state = self._load(self._id(request.get("deployment_id")))
        self._assert_lock(state["deployment_id"])
        if state["state"] not in {"MIGRATION_COMPLETE", "MIGRATION_VERIFIED", "ROLLBACK_STARTED", "FAILED"}:
            raise Rejected("migration downgrade is not permitted in the current transaction state")
        self._save(state, "ROLLBACK_STARTED", recovery="package-declared predecessor downgrade")
        self._run(self._migration_command(state, "downgrade"), cwd=Path(state["target_path"]), env=self._migration_environment(), purpose="approved migration downgrade")
        predecessor = state["manifest_core"]["database"].get("minimum_compatible_revision") or "20260717_0007"
        if self._alembic_revision(state) != predecessor:
            raise Rejected("migration downgrade did not reach the package predecessor revision")
        return self._save(state, "ROLLED_BACK", database_recovery="downgrade")

    def restore_backup(self, request: dict[str, Any]) -> dict[str, Any]:
        state = self._load(self._id(request.get("deployment_id")))
        self._assert_lock(state["deployment_id"])
        if state["state"] not in {"MIGRATION_COMPLETE", "MIGRATION_VERIFIED", "ROLLBACK_STARTED", "FAILED"}:
            raise Rejected("backup restoration is not permitted in the current transaction state")
        record = state.get("backup")
        if not isinstance(record, dict):
            raise Rejected("verified deployment backup is unavailable")
        path = Path(str(record.get("path") or ""))
        if path.parent.resolve() != self.paths.backups.resolve() or path.is_symlink() or not path.is_file() or digest(path) != record.get("sha256"):
            raise Rejected("backup restoration checksum validation failed")
        self._save(state, "ROLLBACK_STARTED", recovery="verified deployment backup restoration")
        environment = self._migration_environment()
        defaults = self._mysql_defaults_file(environment)
        try:
            with gzip.open(path, "rb") as stream:
                result = self.runner(
                    [
                        "/usr/bin/mysql",
                        f"--defaults-extra-file={defaults}",
                        self._database_name(),
                    ],
                    stdin=stream,
                    stderr=subprocess.PIPE,
                    check=False,
                    env=environment,
                )
            if result.returncode:
                raise Rejected("approved backup restoration failed")
            predecessor = state["manifest_core"]["database"].get("minimum_compatible_revision") or "20260717_0007"
            if self._alembic_revision(state) != predecessor:
                raise Rejected("backup restoration did not restore the package predecessor revision")
        except (OSError, Rejected):
            self._save(state, "MANUAL_INTERVENTION_REQUIRED", failure="backup restoration failed")
            self._receipt(state)
            raise
        finally:
            defaults.unlink(missing_ok=True)
        self._save(state, "ROLLED_BACK", database_recovery="verified_backup_restore")
        self._receipt(state)
        self._release_lock(state["deployment_id"])
        return state

    def _run(
        self,
        command: list[str],
        *,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        purpose: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        result = self.runner(command, text=True, capture_output=True, check=False, cwd=cwd, env=env)
        if result.returncode:
            label = purpose or command[0]
            # Process output can contain database URLs or provider credentials.
            # Persist only an allowlisted failure class; never surface raw
            # stderr/stdout, which may contain database URLs or credentials.
            output = f"{result.stderr or ''}\n{result.stdout or ''}".casefold()
            if "login path" in output:
                category = "configured login path unavailable"
            elif "access denied" in output or "error 1045" in output:
                category = "database authentication or authorization failed"
            elif (
                "command denied" in output
                or "couldn\'t execute" in output
                or "could not execute" in output
                or "access violation" in output
            ):
                # mysqldump commonly reports an unavailable SELECT, SHOW VIEW,
                # or TRIGGER privilege as "Couldn\'t execute ... command
                # denied" rather than as MySQL error 1044/1142.  Keep the
                # server output private while making this deployment
                # prerequisite actionable.
                category = "required database read privilege unavailable"
            elif match := re.search(r"(?:got\s+)?error(?:\s+code)?\s*:?\s*([0-9]{3,5})\b", output):
                category = f"MySQL error {match.group(1)}"
            elif "unknown variable" in output:
                category = "approved MySQL defaults configuration is invalid"
            elif "no space left" in output or "got errno" in output:
                category = "approved backup storage write failed"
            elif "process privilege" in output or "permission denied" in output:
                category = "required database privilege unavailable"
            elif "can\'t connect" in output or "connection refused" in output:
                category = "database connectivity failed"
            elif "unknown option" in output:
                category = "approved client option unsupported"
            else:
                category = f"approved command exited nonzero (exit status {result.returncode})"
            raise Rejected(f"approved command failed: {label} ({category})")
        return result

    def _service_runtime_environment(self) -> dict[str, str]:
        """Return the running service environment without displaying its secrets.

        The isolated process must see exactly the production settings that
        systemd supplied to the live API, including database connectivity, but
        neither this method nor its caller serializes any environment values.
        """
        result = self._run(
            ["/bin/systemctl", "show", "--property=MainPID", "--value", SERVICE],
            purpose="service runtime environment lookup",
        )
        pid = result.stdout.strip()
        if not pid.isdecimal() or int(pid) <= 1:
            raise Rejected("active service MainPID is unavailable for staged validation")
        try:
            raw = (self.paths.proc / pid / "environ").read_bytes()
        except OSError as exc:
            raise Rejected("active service environment is unavailable for staged validation") from exc
        environment: dict[str, str] = {}
        for entry in raw.split(b"\0"):
            if not entry or b"=" not in entry:
                continue
            key, value = entry.split(b"=", 1)
            try:
                name = key.decode("ascii")
                environment[name] = os.fsdecode(value)
            except UnicodeDecodeError as exc:
                raise Rejected("active service environment has an invalid variable name") from exc
        if environment.get("EOAT_API_ENVIRONMENT", "").strip().casefold() != "production":
            raise Rejected("active service environment is not production")
        if environment.get("EOAT_API_WRITES_ENABLED", "false").strip().casefold() in {"1", "true", "yes", "on"}:
            raise Rejected("active service environment enables writes")
        return environment

    @staticmethod
    def _validate_health_payload(state: dict[str, Any], health: dict[str, Any], *, target_release: bool) -> None:
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

    def _validate_health(self, state: dict[str, Any], *, target_release: bool) -> None:
        result = self._run(
            ["/usr/bin/curl", "--fail", "--silent", "--max-time", "10", "http://127.0.0.1:8765/api/v1/health"]
        )
        try:
            health = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise Rejected("health endpoint did not return JSON") from exc
        self._validate_health_payload(state, health, target_release=target_release)

    def _validate_staged_runtime(self, state: dict[str, Any], staging: Path) -> dict[str, Any]:
        """Run the staged API on an ephemeral localhost socket under its service account."""
        environment = self._service_runtime_environment()
        result = self._run(
            [
                "/usr/sbin/runuser",
                "--preserve-environment",
                "--user",
                SERVICE_ACCOUNT,
                "--",
                str(staging / "venv" / "bin" / "python"),
                "-c",
                STAGED_RUNTIME_VALIDATION,
            ],
            cwd=staging,
            env=environment,
            purpose="staged localhost runtime validation",
        )
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise Rejected("staged runtime validation did not return JSON") from exc
        if not isinstance(payload, dict):
            raise Rejected("staged runtime validation returned an invalid document")
        health, version = payload.get("health"), payload.get("version")
        self._validate_health_payload(state, health, target_release=True)
        if not isinstance(version, dict):
            raise Rejected("staged version endpoint returned an invalid document")
        for field, expected in {
            "application_version": state["version"],
            "release_id": state["release_id"],
            "build_id": state["build_id"],
        }.items():
            if version.get(field) != expected:
                raise Rejected(f"staged version metadata {field} does not match release")
        expected_schema = state["manifest_core"]["database"]["target_revision"]
        if version.get("database_schema_revision") != expected_schema:
            raise Rejected("staged version metadata schema does not match manifest")
        return {
            "bind": "127.0.0.1:ephemeral",
            "environment": health["environment"],
            "writes_enabled": health["writes_enabled"],
            "database_reachable": health["database_reachable"],
            "schema_revision": health["current_schema_revision"],
            "application_version": health["application_version"],
            "release_id": health["release_id"],
            "build_id": health["build_id"],
            "commit_sha": state["commit_sha"],
        }

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
        decision = request.get("migration_decision")
        if decision not in {"NOT_REQUIRED", "REQUIRED"}:
            raise Rejected("invalid migration_decision")
        state = {
            "schema_version": 1,
            "deployment_id": deployment_id,
            "version": version,
            "commit_sha": commit,
            "artifact_filename": artifact,
            "artifact_sha256": sha,
            "external_manifest_sha256": external_manifest_sha,
            "migration_decision": decision,
            "previous_target": current,
            "created_at_utc": utc(),
            "executor": executor,
            "events": [],
        }
        self._save(state, "CREATED")
        self._save(state, "PACKAGE_VERIFIED", preflight="client-side verified release and server inspection")
        self._lock(state)
        return self._save(state, "LOCK_ACQUIRED")

    def stage(self, request: dict[str, Any]) -> dict[str, Any]:
        state = self._load(self._id(request.get("deployment_id")))
        self._assert_lock(state["deployment_id"])
        if state.get("migration_decision") == "NOT_REQUIRED":
            if state["state"] != "LOCK_ACQUIRED":
                raise Rejected("transaction is not ready for staging")
            self._save(
                state,
                "BACKUP_CREATED",
                backup={"database": "NOT_REQUIRED", "reason": "current revision equals target revision"},
            )
        elif state.get("migration_decision") == "REQUIRED":
            if state["state"] != "BACKUP_VERIFIED":
                raise Rejected("migration-bearing deployments require backup verification before staging")
        else:
            raise Rejected("migration-bearing deployments require explicit approved migration flow")
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
        # Ownership is fixed here; no user supplied account or group can reach
        # this command. It occurs before the isolated run so it exercises the
        # same account as the production systemd service.
        self._run(["/usr/bin/chown", "-R", f"{SERVICE_ACCOUNT}:{SERVICE_ACCOUNT}", str(staging)])
        if state.get("migration_decision") == "REQUIRED":
            # The package expects the target schema, so its API cannot pass a
            # truthful health check until the controlled migration completes.
            os.replace(staging, target)
            self._save(
                state,
                "STAGED_VALIDATED",
                target_path=str(target),
                staged_validation={"status": "DEFERRED_UNTIL_MIGRATION_VERIFIED"},
            )
        else:
            staged_validation = self._validate_staged_runtime(state, staging)
            os.replace(staging, target)
            self._save(state, "STAGED_VALIDATED", target_path=str(target), staged_validation=staged_validation)
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
        allowed = {"STAGED_VALIDATED"} if state.get("migration_decision") == "NOT_REQUIRED" else {"MIGRATION_VERIFIED"}
        if state["state"] not in allowed:
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
        self._save(state, "POSTCHECK_PASSED")
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
            "PACKAGE_VERIFIED",
            "LOCK_ACQUIRED",
            "BACKUP_STARTED",
            "BACKUP_CREATED",
            "BACKUP_VERIFIED",
            "ARTIFACT_VERIFIED",
            "RELEASE_EXTRACTED",
            "RUNTIME_READY",
            "STAGED_VALIDATED",
        }:
            raise Rejected("active or completed deployment cannot be aborted")
        if state["state"] == "BACKUP_STARTED":
            partial = (self.paths.backups / f"{state['deployment_id']}-{self._database_name()}-pre-migration.sql.gz").with_suffix(".sql.partial")
            if partial.is_symlink():
                raise Rejected("production backup partial path is unsafe")
            partial.unlink(missing_ok=True)
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
                "PACKAGE_VERIFIED",
                "LOCK_ACQUIRED",
                "BACKUP_CREATED",
                "BACKUP_VERIFIED",
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
            "previous": sorted(protected - {self._current_target(), ""}),
            "eligible": sorted(
                str(p)
                for p in self.paths.releases.iterdir()
                if p.is_dir() and str(p.resolve()) not in protected and not p.name.startswith(".")
            ),
        }

    def self_check(self, _request: dict[str, Any]) -> dict[str, Any]:
        """Root-side provenance proof without making the helper world-readable."""
        implementation_commit = HELPER_IMPLEMENTATION_COMMIT
        if not COMMIT.fullmatch(implementation_commit):
            implementation_commit = "UNEXPANDED_WORKTREE"
        return {
            "helper_version": 2,
            "implementation_commit": implementation_commit,
            "installed_file_sha256": digest(Path(__file__)),
            "policy_version": HELPER_POLICY_VERSION,
            "operations": [
                "begin",
                "stage",
                "activate",
                "status",
                "abort",
                "rollback",
                "recover",
                "backup-production",
                "verify-backup",
                "migration-preflight",
                "apply-migration",
                "verify-migration",
                "downgrade-migration",
                "restore-backup",
                "cleanup-failed-deployment",
                "retention-status",
                "self-check",
            ],
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
            "backup-production": self.backup_production,
            "verify-backup": self.verify_backup,
            "migration-preflight": self.migration_preflight,
            "apply-migration": self.apply_migration,
            "verify-migration": self.verify_migration,
            "downgrade-migration": self.downgrade_migration,
            "restore-backup": self.restore_backup,
            "cleanup-failed-deployment": self.cleanup_failed_deployment,
            "retention-status": self.retention_status,
            "self-check": self.self_check,
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
