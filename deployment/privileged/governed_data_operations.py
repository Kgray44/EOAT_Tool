"""Fail-closed data-operation boundary used by the EOAT root helper.

The caller can select only a named operation, an opaque request identifier and
whether to perform its policy-defined dry run or execute it.  Policy, database
identity, source roots, destinations, candidate and backup receipts are never
accepted from the caller.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


SHA = re.compile(r"^[0-9a-f]{64}$")
REQUEST_ID = re.compile(r"^[a-z0-9][a-z0-9-]{7,63}$")
OPERATIONS = {"import-press-capacity", "migrate-profile-media"}
MODES = {"dry-run", "execute"}


class Rejected(RuntimeError):
    pass


def utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


@dataclass(frozen=True)
class DataOperationPaths:
    root: Path
    lock: Path
    policy_root: Path
    receipts: Path
    transactions: Path
    release: Path

    @classmethod
    def from_deployment_paths(cls, paths: Any) -> "DataOperationPaths":
        return cls(
            root=paths.root,
            lock=paths.lock,
            policy_root=Path("/etc/eoat-atlas/data-operations"),
            receipts=paths.shared / "data-operation-receipts",
            transactions=paths.shared / "data-operation-transactions",
            release=paths.current,
        )


class GovernedDataOperations:
    """Execute only root-owned, pinned policy operations.

    The policy document has an independently checkable canonical payload
    digest.  Linux production additionally requires every policy ancestor and
    the policy itself to be root-owned and non-writable by group or world.
    """

    def __init__(
        self,
        paths: DataOperationPaths,
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        *,
        implementation: Path,
        require_root_ownership: bool | None = None,
    ) -> None:
        self.paths = paths
        self.runner = runner
        self.implementation = implementation.resolve()
        self.require_root_ownership = os.name != "nt" if require_root_ownership is None else require_root_ownership

    @staticmethod
    def _request_id(value: object) -> str:
        if not isinstance(value, str) or not REQUEST_ID.fullmatch(value):
            raise Rejected("invalid data operation request_id")
        return value

    @staticmethod
    def _safe_relative(value: object, *, label: str) -> Path:
        if not isinstance(value, str) or not value or "\\" in value:
            raise Rejected(f"invalid {label}")
        candidate = Path(value)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise Rejected(f"invalid {label}")
        return candidate

    @staticmethod
    def _safe_absolute(value: object, *, label: str) -> Path:
        if not isinstance(value, str) or not value:
            raise Rejected(f"invalid {label}")
        # Policies are consumed on the Linux production host.  Validate their
        # POSIX form explicitly so disposable Windows harnesses exercise the
        # same contract instead of treating `/srv/...` as a relative path.
        candidate = Path(value)
        if not value.startswith("/") or "\\" in value or ".." in value.split("/"):
            raise Rejected(f"invalid {label}")
        return candidate

    def _trusted_file(self, path: Path, *, label: str) -> None:
        if path.is_symlink() or not path.is_file():
            raise Rejected(f"{label} is not a regular file")
        if not self.require_root_ownership:
            return
        root = self.paths.policy_root.resolve()
        try:
            path.resolve(strict=True).relative_to(root)
        except ValueError as exc:
            raise Rejected(f"{label} escapes the approved policy root") from exc
        for item in (root, *path.resolve().parents):
            if item == root.parent:
                break
            stat = item.stat()
            if stat.st_uid != 0 or stat.st_mode & 0o022:
                raise Rejected("policy ownership or permissions are unsafe")

    def _policy_path(self, operation: str) -> Path:
        return self.paths.policy_root / f"{operation}.json"

    def _policy(self, operation: str) -> tuple[dict[str, Any], str]:
        path = self._policy_path(operation)
        self._trusted_file(path, label="operation policy")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise Rejected("operation policy is invalid") from exc
        if not isinstance(value, dict) or set(value) != {
            "schema_version", "operation", "helper_sha256", "payload", "payload_sha256"
        }:
            raise Rejected("operation policy has an unsupported shape")
        payload = value["payload"]
        if (
            value["schema_version"] != 1
            or value["operation"] != operation
            or not isinstance(payload, dict)
            or not isinstance(value["helper_sha256"], str)
            or not SHA.fullmatch(value["helper_sha256"])
            or not isinstance(value["payload_sha256"], str)
            or not SHA.fullmatch(value["payload_sha256"])
            or value["helper_sha256"] != digest(self.implementation)
            or value["payload_sha256"] != hashlib.sha256(canonical_json(payload)).hexdigest()
        ):
            raise Rejected("operation policy hash or helper binding is invalid")
        self._validate_payload(operation, payload)
        return payload, value["payload_sha256"]

    def _validate_payload(self, operation: str, payload: dict[str, Any]) -> None:
        common = {
            "release_id", "application_version", "schema_revision", "database_identity",
            "backup_receipt", "backup_receipt_sha256", "candidate", "candidate_sha256",
            "rollback", "dry_run_max_age_seconds",
        }
        required = common | (
            {"workbook", "master_press_list", "plant_code", "excluded_machine_numbers"}
            if operation == "import-press-capacity"
            else {"source_roots", "target_root"}
        )
        if set(payload) != required:
            raise Rejected("operation policy payload has unsupported fields")
        if (
            not isinstance(payload["release_id"], str)
            or not isinstance(payload["application_version"], str)
            or not isinstance(payload["schema_revision"], str)
            or payload["database_identity"] != "eoat_atlas_prod"
            or not isinstance(payload["rollback"], str)
            or not isinstance(payload["dry_run_max_age_seconds"], int)
            or not 1 <= payload["dry_run_max_age_seconds"] <= 86400
        ):
            raise Rejected("operation policy contains invalid release or database identity")
        for key in ("backup_receipt", "candidate"):
            self._safe_relative(payload[key], label=key)
        for key in ("backup_receipt_sha256", "candidate_sha256"):
            if not isinstance(payload[key], str) or not SHA.fullmatch(payload[key]):
                raise Rejected(f"invalid {key}")
        if operation == "import-press-capacity":
            self._safe_relative(payload["workbook"], label="workbook")
            self._safe_relative(payload["master_press_list"], label="master_press_list")
            if payload["plant_code"] != "P4" or payload["excluded_machine_numbers"] != ["6", "8", "24", "64", "70", "72"]:
                raise Rejected("capacity policy does not preserve the approved scope")
        else:
            roots = payload["source_roots"]
            if not isinstance(roots, list) or not roots:
                raise Rejected("media policy has no approved source root")
            for root in roots:
                self._safe_absolute(root, label="source_root")
            self._safe_absolute(payload["target_root"], label="target_root")

    def _root_member(self, relative: object, *, label: str, must_exist: bool = True) -> Path:
        candidate = self.paths.root / self._safe_relative(relative, label=label)
        try:
            resolved = candidate.resolve(strict=must_exist)
            resolved.relative_to(self.paths.root.resolve())
        except (OSError, RuntimeError, ValueError) as exc:
            raise Rejected(f"{label} escapes the governed root") from exc
        if must_exist and (resolved.is_symlink() or not resolved.is_file()):
            raise Rejected(f"{label} is not a regular governed file")
        return resolved

    def _backup(self, payload: dict[str, Any]) -> Path:
        backup = self._root_member(payload["backup_receipt"], label="backup_receipt")
        if backup.stat().st_size == 0 or digest(backup) != payload["backup_receipt_sha256"]:
            raise Rejected("verified backup receipt is missing or has drifted")
        try:
            record = json.loads(backup.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise Rejected("verified backup receipt is invalid") from exc
        if not isinstance(record, dict) or record.get("database_identity") != "eoat_atlas_prod" or record.get("verified") is not True:
            raise Rejected("verified backup receipt does not prove the production database")
        return backup

    def _candidate(self, payload: dict[str, Any]) -> Path:
        candidate = self._root_member(payload["candidate"], label="candidate")
        if digest(candidate) != payload["candidate_sha256"]:
            raise Rejected("candidate has drifted from the approved policy")
        return candidate

    def _state_path(self, request_id: str, suffix: str) -> Path:
        return self.paths.transactions / f"{request_id}.{suffix}.json"

    @staticmethod
    def _atomic(path: Path, value: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, sort_keys=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)

    def _acquire_lock(self, state: dict[str, Any]) -> None:
        self.paths.lock.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(self.paths.lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640)
        except FileExistsError as exc:
            raise Rejected("deployment or data-operation lock is held") from exc
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(state, stream, sort_keys=True)

    def _release_lock(self, request_id: str) -> None:
        try:
            value = json.loads(self.paths.lock.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise Rejected("data-operation lock is malformed") from exc
        if value.get("request_id") != request_id:
            raise Rejected("data-operation lock belongs to another transaction")
        self.paths.lock.unlink()

    def _command(self, operation: str, payload: dict[str, Any], *, execute: bool) -> list[str]:
        release = self.paths.release.resolve(strict=True)
        if release.is_symlink() or not release.is_dir() or not (release / "release_manifest.json").is_file():
            raise Rejected("active release is unavailable for governed data operation")
        receipt_dir = self.paths.receipts / operation
        if operation == "import-press-capacity":
            command = [
                "/usr/bin/python3", str(release / "tools/migration/press_capacity_import.py"),
                str(self._root_member(payload["workbook"], label="workbook")),
                "--plant-code", "P4", "--master-press-list", str(self._root_member(payload["master_press_list"], label="master_press_list")),
                "--receipt-directory", str(receipt_dir),
            ]
        else:
            command = [
                "/usr/bin/python3", str(release / "tools/migration/media_migration.py"),
                "--receipt-directory", str(receipt_dir), "--target-root", str(payload["target_root"]),
            ]
            for root in payload["source_roots"]:
                command.extend(["--source-root", str(root)])
        if execute:
            command.append("--execute")
            if operation == "migrate-profile-media":
                command.extend(["--database-backup-receipt", str(self._backup(payload))])
        return command

    def _run(self, operation: str, payload: dict[str, Any], *, execute: bool) -> dict[str, Any]:
        result = self.runner(self._command(operation, payload, execute=execute), text=True, capture_output=True, check=False)
        if result.returncode:
            raise Rejected("approved governed data command failed")
        try:
            output = json.loads(result.stdout)
        except (TypeError, json.JSONDecodeError) as exc:
            raise Rejected("approved governed data command returned invalid output") from exc
        if not isinstance(output, dict) or output.get("status") not in {"DRY_RUN_COMPLETE", "COMPLETED", "SAFE_STOP_ALREADY_IMPORTED"}:
            raise Rejected("approved governed data command reported unsafe state")
        return {"status": output["status"], "receipt": Path(str(output.get("receipt", ""))).name}

    def _fresh_dry_run(self, request_id: str, operation: str, policy_hash: str) -> dict[str, Any]:
        path = self._state_path(request_id, "dry-run")
        if not path.is_file():
            raise Rejected("fresh governed dry run is required")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            stamp = datetime.fromisoformat(value["completed_at_utc"].replace("Z", "+00:00"))
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise Rejected("governed dry-run receipt is invalid") from exc
        if value.get("operation") != operation or value.get("policy_sha256") != policy_hash:
            raise Rejected("governed dry-run policy binding is stale")
        return value | {"age_seconds": (datetime.now(timezone.utc) - stamp).total_seconds()}

    def dispatch(self, request: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(request, dict) or set(request) != {"operation", "request_id", "mode"}:
            raise Rejected("unknown data-operation request fields")
        operation, mode = request.get("operation"), request.get("mode")
        if operation not in OPERATIONS or mode not in MODES:
            raise Rejected("unsupported privileged operation")
        request_id = self._request_id(request.get("request_id"))
        payload, policy_hash = self._policy(operation)
        self._candidate(payload)
        self._backup(payload)
        if mode == "execute":
            dry = self._fresh_dry_run(request_id, operation, policy_hash)
            if dry["age_seconds"] > payload["dry_run_max_age_seconds"]:
                raise Rejected("governed dry run is no longer fresh")
            existing = self.paths.receipts / f"{request_id}.json"
            if existing.is_file():
                try:
                    prior = json.loads(existing.read_text(encoding="utf-8"))
                except json.JSONDecodeError as exc:
                    raise Rejected("existing data-operation receipt is invalid") from exc
                if prior.get("policy_sha256") == policy_hash and prior.get("state") == "COMPLETED":
                    return {"operation": operation, "request_id": request_id, "state": "ALREADY_COMPLETED"}
                raise Rejected("request_id already has an incompatible receipt")
        state = {"operation": operation, "request_id": request_id, "mode": mode, "policy_sha256": policy_hash, "started_at_utc": utc()}
        self._acquire_lock(state)
        try:
            result = self._run(operation, payload, execute=mode == "execute")
            state.update(result, state="COMPLETED", completed_at_utc=utc())
            if mode == "dry-run":
                self._atomic(self._state_path(request_id, "dry-run"), state)
            else:
                state["rollback"] = payload["rollback"]
                receipt = self.paths.receipts / f"{request_id}.json"
                if receipt.exists():
                    raise Rejected("data-operation receipt already exists")
                self._atomic(receipt, state)
            return state
        finally:
            self._release_lock(request_id)
