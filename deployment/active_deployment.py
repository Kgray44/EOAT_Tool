"""Phase 3 client-side coordinator for the fixed privileged deployment helper.

The coordinator has no root capability itself.  It verifies release assets
locally, uploads only exact filenames into the non-final incoming directory,
then invokes the tightly scoped helper with a bounded structured request.
Activation is always a separate explicit command.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import shlex
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .common import DeploymentError, redact_text, utc_text, write_json_atomic
from .manifest import validate_external_manifest
from .release_manager import validate_deployment_archive
from .server_updater import ServerConfig, inspect_server, ssh_host_key_status

HELPER = "/usr/local/libexec/eoat-atlas/eoat_atlas_deploy_helper.py"
PYTHON = "/usr/bin/python3"
DEPLOYMENT_ID = re.compile(r"^deploy-[0-9]{8}t[0-9]{6}z-[0-9a-f]{7}$")


@dataclass(frozen=True)
class ActiveReceipt:
    deployment_id: str
    state: str
    receipt_path: Path


class PrivilegedHelperClient:
    """Strict SSH/SCP transport with no arbitrary remote command interface."""

    def __init__(self, config: ServerConfig, runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run):
        self.config, self._runner = config, runner

    @property
    def host(self) -> str:
        return f"{self.config.username}@{self.config.hostname}" if self.config.username else self.config.hostname

    def _ssh_prefix(self) -> list[str]:
        return ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes", "-p", str(self.config.port), self.host]

    def _run(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        try:
            result = self._runner(command, text=True, capture_output=True, check=False)
        except OSError as exc:
            raise DeploymentError(f"deployment transport is unavailable: {exc}") from exc
        if result.returncode:
            raise DeploymentError(redact_text((result.stderr or result.stdout or "remote command failed").strip()))
        return result

    def invoke(self, request: dict[str, Any]) -> dict[str, Any]:
        raw = json.dumps(request, sort_keys=True, separators=(",", ":")).encode("utf-8")
        encoded = base64.b64encode(raw).decode("ascii")
        remote = shlex.join(["sudo", "-n", PYTHON, HELPER, "--request-b64", encoded])
        result = self._run([*self._ssh_prefix(), remote])
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise DeploymentError("privileged helper did not return JSON") from exc
        if not isinstance(payload, dict):
            raise DeploymentError("privileged helper returned an invalid response")
        return payload

    def upload(self, local: Path, remote_name: str) -> None:
        if not local.is_file() or not re.fullmatch(r"\.[a-z0-9-]{8,64}\.[A-Za-z0-9._-]{1,220}", remote_name):
            raise DeploymentError("refusing unsafe deployment upload path")
        target = f"{self.host}:{self.config.application_root}/incoming/{remote_name}"
        self._run(
            [
                "scp",
                "-o",
                "BatchMode=yes",
                "-o",
                "StrictHostKeyChecking=yes",
                "-P",
                str(self.config.port),
                str(local),
                target,
            ]
        )


def deployment_id(commit_sha: str) -> str:
    identifier = (
        f"deploy-{utc_text().replace('-', '').replace(':', '').replace('T', 't').replace('Z', 'z')}-{commit_sha[:7]}"
    )
    if not DEPLOYMENT_ID.fullmatch(identifier):
        raise DeploymentError("generated deployment identifier is invalid")
    return identifier


def _receipt_path(root: Path, identifier: str) -> Path:
    return root / ".local" / "active-deployment-receipts" / f"{identifier}.json"


def _write_receipt(root: Path, identifier: str, payload: dict[str, Any]) -> ActiveReceipt:
    path = _receipt_path(root, identifier)
    payload["receipt_path"] = str(path)
    payload["ended_at_utc"] = utc_text()
    write_json_atomic(path, payload)
    return ActiveReceipt(identifier, str(payload.get("state") or "UNKNOWN"), path)


def _validated_target(release_dir: Path, external: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], Path]:
    core, artifact = validate_external_manifest(external)
    archive = release_dir / str(artifact["filename"])
    checksum = release_dir / f"{artifact['filename']}.sha256"
    manifest = release_dir / "release_manifest.json"
    if not archive.is_file() or not checksum.is_file() or not manifest.is_file():
        raise DeploymentError("verified release cache is incomplete")
    validate_deployment_archive(archive, manifest, checksum)
    return core, artifact, archive


def stage_release(root: Path, release_dir: Path, external: dict[str, Any], config: ServerConfig) -> ActiveReceipt:
    """Perform preflight and stage one verified release; never activate it."""
    core, artifact, archive = _validated_target(release_dir, external)
    host_key = ssh_host_key_status(config)
    if not host_key.known:
        raise DeploymentError("SSH host key is not trusted; staging stopped before connection")
    inspection = inspect_server(config, core, archive)
    if inspection["blocking_failures"]:
        raise DeploymentError(
            "deployment preflight has blocking failures: " + "; ".join(inspection["blocking_failures"])
        )
    migration = inspection.get("migration_requirement", {})
    if migration.get("status") not in {"NOT_REQUIRED", "PASS"}:
        raise DeploymentError("Phase 3 staging permits only a verified migration-not-required release")
    identifier = deployment_id(str(core["commit_sha"]))
    helper = PrivilegedHelperClient(config)
    request = {
        "operation": "begin",
        "deployment_id": identifier,
        "version": core["version"],
        "commit_sha": core["commit_sha"],
        "artifact_filename": artifact["filename"],
        "artifact_sha256": artifact["sha256"],
        "external_manifest_sha256": hashlib.sha256((release_dir / "release_manifest.json").read_bytes()).hexdigest(),
        "migration_decision": "NOT_REQUIRED",
    }
    started = utc_text()
    helper.invoke(request)
    try:
        helper.upload(archive, f".{identifier}.{artifact['filename']}")
        helper.upload(release_dir / "release_manifest.json", f".{identifier}.release_manifest.json")
        helper.upload(release_dir / f"{artifact['filename']}.sha256", f".{identifier}.{artifact['filename']}.sha256")
        state = helper.invoke({"operation": "stage", "deployment_id": identifier})
    except Exception:
        # Abort is narrowly constrained to pre-activation states.  Preserve the
        # original failure when the transport itself has disappeared.
        try:
            helper.invoke({"operation": "abort", "deployment_id": identifier})
        except DeploymentError:
            pass
        raise
    return _write_receipt(
        root,
        identifier,
        {
            "schema_version": 1,
            "mode": "STAGE_ONLY",
            "started_at_utc": started,
            "state": state.get("state"),
            "selected_release": {
                "version": core["version"],
                "commit_sha": core["commit_sha"],
                "release_id": core["release_id"],
                "build_id": core["build_id"],
            },
            "artifact": artifact,
            "server": config.hostname,
            "preflight": inspection,
            "activation_performed": False,
            "production_symlink_changed": False,
            "production_service_restarted": False,
            "production_database_written": False,
        },
    )


def helper_operation(root: Path, config: ServerConfig, operation: str, identifier: str) -> ActiveReceipt:
    if operation not in {"activate", "status", "rollback", "recover", "abort"} or not DEPLOYMENT_ID.fullmatch(
        identifier
    ):
        raise DeploymentError("unsafe Phase 3 helper operation")
    if not ssh_host_key_status(config).known:
        raise DeploymentError("SSH host key is not trusted; command stopped before connection")
    started = utc_text()
    state = PrivilegedHelperClient(config).invoke({"operation": operation, "deployment_id": identifier})
    return _write_receipt(
        root,
        identifier,
        {
            "schema_version": 1,
            "mode": operation.upper(),
            "started_at_utc": started,
            "state": state.get("state"),
            "helper_state": state,
            "server": config.hostname,
            "activation_performed": operation == "activate",
        },
    )
